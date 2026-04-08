import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone

from arq.connections import ArqRedis
from fastapi import APIRouter, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from app.config import MAX_FILE_SIZE, WHISPER_MODEL
from app.models import TaskResponse, TaskStatus
from app.storage import generate_srt, load_result, save_upload
from app.tasks import AVAILABLE_MODELS

router = APIRouter(prefix="/api")

# Stream state
_stream_lock = asyncio.Lock()
_stream_process = None

WHISPER_STREAM_BIN = os.environ.get("WHISPER_STREAM_BIN", "/opt/homebrew/bin/whisper-stream")
STREAM_MODEL_PATH = os.environ.get(
    "STREAM_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "models", "ggml-small.bin"),
)


@router.websocket("/stream")
async def websocket_stream(ws: WebSocket):
    global _stream_process
    await ws.accept()

    if _stream_lock.locked():
        await ws.send_json({"type": "error", "message": "已有其他使用者正在使用，請稍後再試"})
        await ws.close()
        return

    async with _stream_lock:
        process = None
        stdout_task = None
        try:
            while True:
                data = json.loads(await ws.receive_text())

                if data["action"] == "start":
                    if process:
                        process.terminate()
                        await process.wait()

                    lang = data.get("language", "zh")
                    await ws.send_json({"type": "status", "message": "loading"})

                    process = await asyncio.create_subprocess_exec(
                        WHISPER_STREAM_BIN,
                        "-m", STREAM_MODEL_PATH,
                        "-l", lang,
                        "--step", "3000",
                        "--length", "10000",
                        "--keep", "200",
                        "--keep-context",
                        "-t", "4",
                        "-c", "-1",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _stream_process = process

                    async def read_stdout():
                        try:
                            async for line in process.stdout:
                                text = line.decode("utf-8", errors="replace").strip()
                                text = re.sub(r"\[[\d:.]+\s*-->\s*[\d:.]+\]\s*", "", text)
                                if text and not text.startswith(("init:", "whisper_", "ggml_", "load_")):
                                    await ws.send_json({"type": "transcript", "text": text})
                        except Exception:
                            pass

                    stdout_task = asyncio.create_task(read_stdout())
                    await ws.send_json({"type": "status", "message": "started"})

                elif data["action"] == "stop":
                    if process:
                        process.terminate()
                        await process.wait()
                        process = None
                        _stream_process = None
                    if stdout_task:
                        stdout_task.cancel()
                        stdout_task = None
                    await ws.send_json({"type": "status", "message": "stopped"})

        except (WebSocketDisconnect, Exception):
            pass
        finally:
            if process:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                _stream_process = None
            if stdout_task:
                stdout_task.cancel()


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
