# Whisper 語音轉文字服務

一鍵啟動的語音轉文字服務，基於 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 引擎，支援中英混用。

## 快速開始

```bash
# 1. 啟動服務
docker compose up -d

# 2. 開瀏覽器
open http://localhost:8000
```

首次啟動會自動下載模型（預設 base，142MB），之後會快取不再重複下載。

## 功能

- **拖曳上傳**音檔或影片（MP3, WAV, MP4, M4A, FLAC, OGG）
- **前端切換模型** — 從 Tiny 到 Large-v3，依需求選擇精度和速度
- **即時進度**顯示
- **下載結果** — TXT 純文字 / SRT 字幕 / JSON 結構化
- **非同步處理** — 上傳後排隊，不阻塞

## 模型選擇

在前端頁面上方可以直接點選模型：

| 模型 | 大小 | 速度 | 品質 | 適合場景 |
|------|------|------|------|---------|
| Tiny | 75 MB | 最快 | 低 | 快速測試 |
| Base | 142 MB | 很快 | 普通 | 一般用途（預設） |
| Small | 466 MB | 快 | 堪用 | 日常使用 |
| Medium | 1.5 GB | 中等 | 好 | 會議記錄 |
| Large-v2 | 2.9 GB | 慢 | 很好 | 技術內容（中英混用最佳） |
| Large-v3 | 2.9 GB | 慢 | 最佳 | 最高精度（有幻覺風險） |
| Large-v3 Turbo | 1.6 GB | 快 | 很好 | 精度與速度兼顧 |

> 首次選用新模型時，Worker 會自動下載（僅一次），後續直接從快取載入。

## 架構

```
瀏覽器 (localhost:8000)
  │
  ├─ 靜態頁面 (index.html)
  │
  └─ REST API
       │
       ├─ FastAPI (api container)
       │    ├─ POST /api/transcribe    上傳音檔
       │    ├─ GET  /api/tasks/{id}    查詢狀態
       │    ├─ GET  /api/tasks/{id}/download  下載結果
       │    └─ GET  /api/models        模型列表
       │
       ├─ Redis (redis container)
       │    └─ 任務佇列 + 狀態快取
       │
       └─ Worker (worker container)
            └─ faster-whisper 轉錄引擎
```

## 設定

### 環境變數 (.env)

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `WHISPER_MODEL` | `base` | 預設模型（前端可覆蓋） |
| `DEVICE` | `auto` | `auto` / `cuda` / `cpu` |
| `COMPUTE_TYPE` | `int8` | `int8`(CPU) / `float16`(GPU) |

### 啟用 GPU

有 NVIDIA GPU + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) 的話：

1. 編輯 `docker-compose.yml`，取消 worker 的 GPU 註解：

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

2. 修改 `.env`：

```
DEVICE=cuda
COMPUTE_TYPE=float16
```

3. 重啟：

```bash
docker compose up -d
```

## API

```bash
# 上傳（預設模型）
curl -X POST http://localhost:8000/api/transcribe \
  -F "file=@audio.wav"

# 上傳（指定模型）
curl -X POST "http://localhost:8000/api/transcribe?model=large-v2" \
  -F "file=@audio.wav"

# 查詢狀態
curl http://localhost:8000/api/tasks/{task_id}

# 下載結果
curl http://localhost:8000/api/tasks/{task_id}/download?format=txt
curl http://localhost:8000/api/tasks/{task_id}/download?format=srt
curl http://localhost:8000/api/tasks/{task_id}/download?format=json

# 模型列表
curl http://localhost:8000/api/models
```

## 停止服務

```bash
docker compose down
```

清除所有資料（模型快取、上傳檔案、轉錄結果）：

```bash
docker compose down -v
```

---

## CLI 工具（本地 whisper.cpp）

除了 Docker 服務，也可以直接用 whisper.cpp CLI：

```bash
# 一鍵轉錄
./run.sh <影片或音頻檔案>

# 範例
./run.sh ~/Desktop/lecture.mov
./run.sh recording.wav
```

### CLI 參數

| 參數 | 說明 | 範例 |
|------|------|------|
| `-m` | 模型路徑 | `models/ggml-large-v2.bin` |
| `-f` | 音頻檔案 | `output.wav` |
| `-l` | 語言 | `zh`（中文）、`en`（英文）、`auto` |
| `-osrt` | 輸出 SRT 字幕 | 自動產生 `.srt` |
| `-otxt` | 輸出純文字 | 自動產生 `.txt` |

### 批次處理

```bash
for f in ~/Desktop/*.mov; do ./run.sh "$f"; done
```

## 技術筆記

- whisper.cpp 使用 Metal GPU 加速，比 Python 版快 10x+
- faster-whisper (Docker 版) 使用 CTranslate2，比原版 Whisper 快 4-8x
- 音頻必須是 16kHz 單聲道 WAV（ffmpeg 自動轉換）
- 詳細模型比較見 [MODEL_COMPARISON.md](MODEL_COMPARISON.md)
