import asyncio
import io
import json
import logging
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone

from arq.connections import ArqRedis
from fastapi import APIRouter, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from app.config import COMPUTE_TYPE, DEVICE, MAX_FILE_SIZE, WHISPER_MODEL
from app.models import TaskResponse, TaskStatus
from app.storage import generate_srt, load_result, save_upload
from app.tasks import AVAILABLE_MODELS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Stream: 共用一個 model instance（lazy load）
_stream_model = None


def _get_stream_model():
    global _stream_model
    if _stream_model is None:
        from faster_whisper import WhisperModel
        device = DEVICE
        compute_type = COMPUTE_TYPE
        if device == "auto":
            try:
                import ctranslate2
                device = "cuda" if "cuda" in ctranslate2.get_supported_compute_types("cuda") else "cpu"
            except Exception:
                device = "cpu"
        if device == "cuda" and compute_type == "int8":
            compute_type = "float16"
        # 即時轉錄用 base 模型（速度優先）
        stream_model_id = os.environ.get("STREAM_MODEL", "base")
        logger.info("Loading stream model=%s device=%s compute_type=%s", stream_model_id, device, compute_type)
        _stream_model = WhisperModel(stream_model_id, device=device, compute_type=compute_type)
    return _stream_model


@router.websocket("/stream")
async def websocket_stream(ws: WebSocket):
    await ws.accept()

    model = None
    language = "zh"
    is_streaming = False
    chunk_queue: asyncio.Queue = asyncio.Queue()
    worker_task: asyncio.Task | None = None

    async def chunk_worker():
        """背景 worker：從 queue 取 chunk，轉錄後推回前端"""
        while True:
            chunk = await chunk_queue.get()
            try:
                text = await asyncio.to_thread(
                    _transcribe_chunk, model, chunk, language
                )
                if text.strip():
                    logger.info("Transcribed: '%s'", text.strip()[:100])
                    await ws.send_json({"type": "transcript", "text": text.strip()})
            except Exception as e:
                logger.warning("Stream transcribe error: %s", e)
            finally:
                chunk_queue.task_done()

    try:
        while True:
            msg = await ws.receive()

            if "text" in msg:
                data = json.loads(msg["text"])

                if data["action"] == "start":
                    language = data.get("language", "zh")
                    if language == "auto":
                        language = None
                    await ws.send_json({"type": "status", "message": "loading"})
                    model = await asyncio.to_thread(_get_stream_model)
                    is_streaming = True
                    worker_task = asyncio.create_task(chunk_worker())
                    await ws.send_json({"type": "status", "message": "started"})

                elif data["action"] == "stop":
                    is_streaming = False
                    if worker_task:
                        worker_task.cancel()
                        worker_task = None
                    await ws.send_json({"type": "status", "message": "stopped"})

            elif "bytes" in msg:
                audio = msg["bytes"]
                logger.info("Received chunk: %d bytes, streaming=%s", len(audio), is_streaming)
                if is_streaming and model is not None and len(audio) >= 1000:
                    await chunk_queue.put(audio)

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if worker_task:
            worker_task.cancel()


def _transcribe_chunk(model, audio_bytes: bytes, language) -> str:
    """把音訊片段轉成文字（同步，跑在 thread 裡）"""
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(audio_bytes)
        webm_path = f.name

    wav_path = webm_path.replace(".webm", ".wav")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", webm_path, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_path],
            capture_output=True,
        )
        if result.returncode != 0:
            return ""  # 跳過無法轉換的 chunk

        segments, _ = model.transcribe(
            wav_path,
            language=language,
            vad_filter=False,
            condition_on_previous_text=True,
        )
        return "".join(seg.text for seg in segments)
    finally:
        for p in (webm_path, wav_path):
            try:
                os.unlink(p)
            except OSError:
                pass


@router.get("/models")
async def list_models():
    return {"models": AVAILABLE_MODELS, "default": WHISPER_MODEL}


@router.post("/transcribe", response_model=TaskResponse)
async def create_transcription(request: Request, file: UploadFile, model: str = ""):
    allowed_types = ("audio/", "video/", "application/octet-stream")
    allowed_exts = (".mp3", ".wav", ".mp4", ".m4a", ".flac", ".ogg", ".webm", ".aac", ".wma")
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content_ok = not file.content_type or file.content_type.startswith(allowed_types)
    ext_ok = f".{ext}" in allowed_exts if ext else True
    if not (content_ok or ext_ok):
        raise HTTPException(400, "Only audio/video files are accepted")

    task_id = str(uuid.uuid4())
    redis: ArqRedis = request.app.state.redis
    pool: ArqRedis = request.app.state.arq_pool

    file_path = await save_upload(file, task_id)

    now = datetime.now(timezone.utc).isoformat()
    await redis.hset(f"task:{task_id}", mapping={
        "status": "queued",
        "progress": "0",
        "created_at": now,
        "filename": file.filename or "unknown",
    })
    await redis.expire(f"task:{task_id}", 86400)

    selected_model = model or WHISPER_MODEL
    await pool.enqueue_job("transcribe_audio", task_id, file_path, selected_model)

    return TaskResponse(task_id=task_id, status="queued")


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(request: Request, task_id: str):
    redis: ArqRedis = request.app.state.redis
    raw = await redis.hgetall(f"task:{task_id}")

    if not raw:
        raise HTTPException(404, "Task not found")

    data = {}
    for k, v in raw.items():
        key = k.decode() if isinstance(k, bytes) else k
        val = v.decode() if isinstance(v, bytes) else v
        data[key] = val

    result = None
    if data.get("result"):
        result = json.loads(data["result"])

    return TaskStatus(
        task_id=task_id,
        status=data.get("status", "unknown"),
        progress=int(data.get("progress", 0)),
        filename=data.get("filename", ""),
        error=data.get("error", ""),
        result=result,
    )


@router.get("/tasks/{task_id}/download")
async def download_result(task_id: str, format: str = "txt"):
    result = load_result(task_id)
    if result is None:
        raise HTTPException(404, "Result not found")

    if format == "json":
        return result
    elif format == "srt":
        srt = generate_srt(result.get("segments", []))
        return PlainTextResponse(srt, media_type="text/plain",
                                 headers={"Content-Disposition": f"attachment; filename={task_id}.srt"})
    else:
        return PlainTextResponse(result.get("text", ""),
                                 headers={"Content-Disposition": f"attachment; filename={task_id}.txt"})
