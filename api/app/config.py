import os


WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/data/uploads")
RESULT_DIR = os.getenv("RESULT_DIR", "/data/results")
DEVICE = os.getenv("DEVICE", "auto")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
