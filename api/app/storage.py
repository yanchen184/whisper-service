import json
import os
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.config import RESULT_DIR, UPLOAD_DIR


async def save_upload(file: UploadFile, task_id: str) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = Path(file.filename).suffix or ".wav"
    path = os.path.join(UPLOAD_DIR, f"{task_id}{ext}")
    async with aiofiles.open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            await f.write(chunk)
    return path


def save_result(task_id: str, result: dict) -> str:
    os.makedirs(RESULT_DIR, exist_ok=True)
    path = os.path.join(RESULT_DIR, f"{task_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


def get_result_path(task_id: str) -> str | None:
    path = os.path.join(RESULT_DIR, f"{task_id}.json")
    return path if os.path.exists(path) else None


def load_result(task_id: str) -> dict | None:
    path = get_result_path(task_id)
    if path is None:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def generate_srt(segments: list[dict]) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_time(seg["start"])
        end = _format_time(seg["end"])
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


def _format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
