import asyncio
import io
import json
import logging
import os
import subprocess
import threading

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.config import COMPUTE_TYPE, DEVICE, MAX_CHUNK_SIZE, MAX_CONNECTIONS, STREAM_MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_stream_model = None
_model_lock = threading.Lock()
_active_connections = 0


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


@router.get("/health")
async def health():
    if _stream_model is None:
        return JSONResponse({"status": "loading"}, status_code=503)
    return {"status": "ok", "model": STREAM_MODEL}


@router.websocket("/stream")
async def websocket_stream(ws: WebSocket):
    global _active_connections

    if _active_connections >= MAX_CONNECTIONS:
        await ws.accept()
        await ws.send_json({"type": "error", "message": f"伺服器忙碌中（{_active_connections}/{MAX_CONNECTIONS}），請稍後再試"})
        await ws.close()
        return

    await ws.accept()
    _active_connections += 1

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
                        logger.info("Transcribed: '%s'", text.strip()[:100])
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
                data = json.loads(msg["text"])

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
        _active_connections -= 1
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
    segments, _ = model.transcribe(
        wav_io,
        language=language,
        vad_filter=True,
        vad_parameters={
            "threshold": 0.3,
            "min_silence_duration_ms": 300,
            "speech_pad_ms": 200,
        },
        condition_on_previous_text=True,
    )
    return "".join(seg.text for seg in segments)
