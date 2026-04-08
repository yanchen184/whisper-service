import asyncio
import json
import logging
import os
import subprocess
import tempfile

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import COMPUTE_TYPE, DEVICE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

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
        stream_model_id = os.environ.get("STREAM_MODEL", "base")
        logger.info("Loading model=%s device=%s compute_type=%s", stream_model_id, device, compute_type)
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
            return ""

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
