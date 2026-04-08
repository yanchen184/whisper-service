import os

DEVICE = os.getenv("DEVICE", "auto")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")
STREAM_MODEL = os.getenv("STREAM_MODEL", "phate334/Breeze-ASR-25-ct2")
MAX_CONNECTIONS = int(os.getenv("MAX_CONNECTIONS", "20"))
MAX_CHUNK_SIZE = int(os.getenv("MAX_CHUNK_SIZE", str(5 * 1024 * 1024)))  # 5MB
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "zh")

# 前端 VAD（瀏覽器偵測停頓切段）
VAD_SILENCE_THRESHOLD = float(os.getenv("VAD_SILENCE_THRESHOLD", "0.015"))
VAD_SILENCE_DURATION_MS = int(os.getenv("VAD_SILENCE_DURATION_MS", "800"))
VAD_MIN_SPEECH_MS = int(os.getenv("VAD_MIN_SPEECH_MS", "500"))
VAD_MAX_CHUNK_MS = int(os.getenv("VAD_MAX_CHUNK_MS", "10000"))

# 後端 VAD（faster-whisper 過濾靜音段）
BACKEND_VAD_ENABLED = os.getenv("BACKEND_VAD_ENABLED", "true").lower() == "true"
BACKEND_VAD_THRESHOLD = float(os.getenv("BACKEND_VAD_THRESHOLD", "0.3"))
BACKEND_VAD_SILENCE_MS = int(os.getenv("BACKEND_VAD_SILENCE_MS", "300"))
BACKEND_VAD_SPEECH_PAD_MS = int(os.getenv("BACKEND_VAD_SPEECH_PAD_MS", "200"))
