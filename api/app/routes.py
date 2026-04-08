import asyncio
import io
import json
import logging
import os
import subprocess
import threading

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.config import (
    BACKEND_VAD_ENABLED, BACKEND_VAD_SILENCE_MS, BACKEND_VAD_SPEECH_PAD_MS, BACKEND_VAD_THRESHOLD,
    COMPUTE_TYPE, DEFAULT_LANGUAGE, DEVICE, MAX_CHUNK_SIZE, MAX_CONNECTIONS, STREAM_MODEL,
    VAD_MAX_CHUNK_MS, VAD_MIN_SPEECH_MS, VAD_SILENCE_DURATION_MS, VAD_SILENCE_THRESHOLD,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_stream_model = None
_model_lock = threading.Lock()
_connection_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _connection_semaphore
    if _connection_semaphore is None:
        _connection_semaphore = asyncio.Semaphore(MAX_CONNECTIONS)
    return _connection_semaphore


def _get_stream_model():
    global _stream_model
    if _stream_model is not None:
        return _stream_model
    with _model_lock:
        if _stream_model is not None:
            return _stream_model
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
        logger.info("Loading model=%s device=%s compute_type=%s", STREAM_MODEL, device, compute_type)
        _stream_model = WhisperModel(STREAM_MODEL, device=device, compute_type=compute_type)
    return _stream_model


@router.get("/config")
async def get_config():
    return {
        "vad_silence_threshold": VAD_SILENCE_THRESHOLD,
        "vad_silence_duration_ms": VAD_SILENCE_DURATION_MS,
        "vad_min_speech_ms": VAD_MIN_SPEECH_MS,
        "vad_max_chunk_ms": VAD_MAX_CHUNK_MS,
        "default_language": DEFAULT_LANGUAGE,
        "max_connections": MAX_CONNECTIONS,
    }


@router.get("/health")
async def health():
    if _stream_model is None:
        return JSONResponse({"status": "loading"}, status_code=503)
    return {"status": "ok", "model": STREAM_MODEL}


@router.websocket("/stream")
async def websocket_stream(ws: WebSocket):
    sem = _get_semaphore()

    if sem.locked():
        await ws.accept()
        await ws.send_json({"type": "error", "message": f"伺服器忙碌中（已達 {MAX_CONNECTIONS} 人上限），請稍後再試"})
        await ws.close()
        return

    await sem.acquire()
    await ws.accept()

    model = None
    language = "zh"
    is_streaming = False
    chunk_queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    worker_task: asyncio.Task | None = None

    async def chunk_worker():
        try:
            while True:
                chunk = await chunk_queue.get()
                try:
                    text = await asyncio.to_thread(
                        _transcribe_chunk, model, chunk, language
                    )
                    if text.strip():
                        logger.debug("Transcribed: '%s'", text.strip()[:100])
                        await ws.send_json({"type": "transcript", "text": text.strip()})
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning("Stream transcribe error: %s", e)
                finally:
                    chunk_queue.task_done()
        except asyncio.CancelledError:
            pass

    try:
        while True:
            msg = await ws.receive()

            if "text" in msg:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue

                if data.get("action") == "start":
                    language = data.get("language", "zh")
                    if language == "auto":
                        language = None
                    await ws.send_json({"type": "status", "message": "loading"})
                    model = await asyncio.to_thread(_get_stream_model)
                    is_streaming = True
                    worker_task = asyncio.create_task(chunk_worker())
                    await ws.send_json({"type": "status", "message": "started"})

                elif data.get("action") == "stop":
                    is_streaming = False
                    if worker_task:
                        worker_task.cancel()
                        worker_task = None
                    await ws.send_json({"type": "status", "message": "stopped"})

            elif "bytes" in msg:
                audio = msg["bytes"]
                if not is_streaming or model is None:
                    continue
                if len(audio) < 1000 or len(audio) > MAX_CHUNK_SIZE:
                    continue
                if not chunk_queue.full():
                    await chunk_queue.put(audio)

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception:
        logger.exception("WebSocket error")
    finally:
        sem.release()
        if worker_task:
            worker_task.cancel()


def _transcribe_chunk(model, audio_bytes: bytes, language) -> str:
    """用 ffmpeg pipe 模式轉換 webm → wav，不寫暫存檔"""
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"],
        input=audio_bytes,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        return ""

    wav_io = io.BytesIO(result.stdout)
    transcribe_kwargs = {
        "language": language,
        "vad_filter": BACKEND_VAD_ENABLED,
        "condition_on_previous_text": True,
    }
    if BACKEND_VAD_ENABLED:
        transcribe_kwargs["vad_parameters"] = {
            "threshold": BACKEND_VAD_THRESHOLD,
            "min_silence_duration_ms": BACKEND_VAD_SILENCE_MS,
            "speech_pad_ms": BACKEND_VAD_SPEECH_PAD_MS,
        }
    segments, _ = model.transcribe(wav_io, **transcribe_kwargs)
    return "".join(seg.text for seg in segments)
