import logging
from contextlib import asynccontextmanager
from pathlib import Path

from arq.connections import ArqRedis, create_pool, RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import REDIS_URL
from app.routes import router, _get_stream_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


def parse_redis_url(url: str) -> RedisSettings:
    url = url.replace("redis://", "")
    host, port = url.split(":")
    return RedisSettings(host=host, port=int(port))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = parse_redis_url(REDIS_URL)
    pool = await create_pool(settings)
    app.state.redis = pool
    app.state.arq_pool = pool
    logging.getLogger(__name__).info("Pre-loading stream model...")
    _get_stream_model()
    logging.getLogger(__name__).info("Stream model ready")
    yield
    await pool.close()


app = FastAPI(title="Whisper Transcription Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

web_dir = Path("/web")
if not web_dir.exists():
    web_dir = Path(__file__).resolve().parent.parent.parent / "web"
app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="static")
