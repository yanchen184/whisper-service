import os

DEVICE = os.getenv("DEVICE", "auto")
COMPUTE_TYPE = os.getenv("COMPUTE_TYPE", "int8")
STREAM_MODEL = os.getenv("STREAM_MODEL", "phate334/Breeze-ASR-25-ct2")
MAX_CONNECTIONS = int(os.getenv("MAX_CONNECTIONS", "5"))
MAX_CHUNK_SIZE = int(os.getenv("MAX_CHUNK_SIZE", str(5 * 1024 * 1024)))  # 5MB
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
