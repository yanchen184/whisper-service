import logging

from arq import cron
from arq.connections import RedisSettings

from app.config import REDIS_URL
from app.tasks import load_default_model, transcribe_audio

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


def parse_redis_url(url: str) -> RedisSettings:
    url = url.replace("redis://", "")
    host, port = url.split(":")
    return RedisSettings(host=host, port=int(port))


async def startup(ctx: dict) -> None:
    load_default_model(ctx)


class WorkerSettings:
    functions = [transcribe_audio]
    on_startup = startup
    redis_settings = parse_redis_url(REDIS_URL)
    max_jobs = 1
    job_timeout = 3600
