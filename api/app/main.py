import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routes import router, _get_stream_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.getLogger(__name__).info("Pre-loading stream model...")
    _get_stream_model()
    logging.getLogger(__name__).info("Stream model ready")
    yield


app = FastAPI(title="Whisper 即時轉錄服務", lifespan=lifespan)

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
