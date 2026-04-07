import json
import logging
import time

from app.config import COMPUTE_TYPE, DEVICE, WHISPER_MODEL
from app.storage import save_result

logger = logging.getLogger(__name__)


AVAILABLE_MODELS = [
    {"id": "tiny", "name": "Tiny", "size": "75 MB", "speed": "最快", "quality": "低"},
    {"id": "base", "name": "Base", "size": "142 MB", "speed": "很快", "quality": "普通"},
    {"id": "small", "name": "Small", "size": "466 MB", "speed": "快", "quality": "堪用"},
    {"id": "medium", "name": "Medium", "size": "1.5 GB", "speed": "中等", "quality": "好"},
    {"id": "large-v2", "name": "Large-v2", "size": "2.9 GB", "speed": "慢", "quality": "很好"},
    {"id": "large-v3", "name": "Large-v3", "size": "2.9 GB", "speed": "慢", "quality": "最佳（有幻覺風險）"},
    {"id": "large-v3-turbo", "name": "Large-v3 Turbo", "size": "1.6 GB", "speed": "快", "quality": "很好"},
    {"id": "phate334/Breeze-ASR-25-ct2", "name": "Breeze ASR 25 (聯發科)", "size": "3.1 GB", "speed": "慢", "quality": "中英混用最佳"},
]


async def transcribe_audio(ctx: dict, task_id: str, file_path: str, model_id: str = "") -> None:
    redis = ctx["redis"]
    model_id = model_id or WHISPER_MODEL
    model = _get_or_load_model(ctx, model_id)
    key = f"task:{task_id}"

    await redis.hset(key, "status", "processing")
    await redis.hset(key, "progress", "0")

    try:
        start_time = time.time()

        segments_gen, info = model.transcribe(
            file_path,
            language=None,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            word_timestamps=True,
            condition_on_previous_text=True,
        )

        duration = info.duration
        segments = []
        accumulated = 0.0

        for segment in segments_gen:
            segments.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
            })
            accumulated = segment.end
            if duration > 0:
                progress = min(int((accumulated / duration) * 100), 99)
                await redis.hset(key, "progress", str(progress))

        elapsed = time.time() - start_time
        full_text = "".join(seg["text"] for seg in segments)

        result = {
            "text": full_text,
            "segments": segments,
            "language": info.language,
            "duration": duration,
            "elapsed": round(elapsed, 2),
            "model": model_id,
        }

        save_result(task_id, result)

        await redis.hset(key, "status", "completed")
        await redis.hset(key, "progress", "100")
        await redis.hset(key, "result", json.dumps(result, ensure_ascii=False))
        await redis.expire(key, 86400)

        logger.info(
            "Task %s completed: %.1fs audio in %.1fs (%.1fx realtime)",
            task_id, duration, elapsed, duration / elapsed if elapsed > 0 else 0,
        )

    except Exception as e:
        logger.exception("Task %s failed", task_id)
        await redis.hset(key, "status", "failed")
        await redis.hset(key, "error", str(e))
        await redis.expire(key, 86400)


def _get_device_and_compute():
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

    return device, compute_type


def _get_or_load_model(ctx: dict, model_id: str):
    from faster_whisper import WhisperModel

    cache = ctx.setdefault("models", {})
    if model_id in cache:
        return cache[model_id]

    device, compute_type = _get_device_and_compute()
    logger.info("Loading model=%s device=%s compute_type=%s", model_id, device, compute_type)
    model = WhisperModel(model_id, device=device, compute_type=compute_type)
    cache[model_id] = model
    return model


def load_default_model(ctx: dict) -> None:
    _get_or_load_model(ctx, WHISPER_MODEL)
