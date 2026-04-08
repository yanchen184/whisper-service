#!/bin/bash
cd "$(dirname "$0")"

echo "=== Whisper 即時轉錄 (本機模式) ==="
echo ""

source whisper-env/bin/activate

# 確認依賴
pip install -q fastapi uvicorn arq python-multipart aiofiles websockets redis 2>/dev/null

# 確認 whisper-stream
if ! command -v whisper-stream &>/dev/null; then
  echo "錯誤: whisper-stream 未安裝，請執行 brew install whisper-cpp"
  exit 1
fi

# 確認模型
if [ ! -f models/ggml-small.bin ]; then
  echo "錯誤: models/ggml-small.bin 不存在"
  exit 1
fi

echo "啟動 FastAPI (http://localhost:8000)..."
echo "即時轉錄 + 批次轉錄 都在同一個服務"
echo ""
echo "開啟瀏覽器: http://localhost:8000"
echo "切換到「即時轉錄」tab"
echo ""
echo "按 Ctrl+C 停止"

cd api
STREAM_MODEL_PATH="$(dirname "$PWD")/models/ggml-small.bin" \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
