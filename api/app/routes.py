import json
import uuid
from datetime import datetime, timezone

from arq.connections import ArqRedis
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse

from app.config import MAX_FILE_SIZE, WHISPER_MODEL
from app.models import TaskResponse, TaskStatus
from app.storage import generate_srt, load_result, save_upload
from app.tasks import AVAILABLE_MODELS

router = APIRouter(prefix="/api")


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
