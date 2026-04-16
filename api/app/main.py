import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.routes import router, _get_stream_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """啟動時預載所有模型與資料，任何初始化失敗直接終止啟動。"""

    # 1. 預載 Whisper 轉錄模型
    logger.info("預載 Whisper 模型...")
    _get_stream_model()
    logger.info("Whisper 模型就緒")

    # 2. 初始化向量資料庫（驗證 data/*.json 存在、必要時重建 embedding）
    #    run_in_executor 避免阻塞 event loop（embedding 為 CPU bound）
    logger.info("初始化向量資料庫...")
    try:
        from app.vector_store import get_vector_store
        await asyncio.get_running_loop().run_in_executor(None, get_vector_store)
        logger.info("向量資料庫就緒")
    except FileNotFoundError as e:
        logger.critical("啟動失敗：%s", e)
        raise SystemExit(1) from e

    yield


app = FastAPI(title="長照機構評鑑 — 即時語音轉錄與 AI 評鑑意見系統", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
