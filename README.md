# 長照機構評鑑 — 即時語音轉錄與 AI 評鑑意見系統

長照評鑑委員操作介面，支援即時語音轉錄，以及根據評鑑指標自動產製條列式評量意見。

---

## 技術決策摘要

| 面向 | 選型 | 決策理由 |
|------|------|---------|
| 語音辨識 | faster-whisper（CTranslate2 量化） | 比原版 Whisper 快 2–4 倍、記憶體減半；繁中模型 `Breeze-ASR-25-ct2` 針對台灣口音微調 |
| GPU 彈性 | 雙後端切換（faster-whisper / whisper.cpp） | NVIDIA 走 CUDA，AMD 走 Vulkan，環境變數切換不改程式碼 |
| 評鑑意見生成 | RAG（ChromaDB + SentenceTransformer + vLLM） | LLM 不知道衛福部最新指標，先查資料再生成，確保內容符合當年度評鑑標準 |
| Few-shot 策略 | 語意相似度排序，非隨機抽取 | 用委員 transcript 對 1578 筆歷年意見做向量搜尋，最相關的 3 筆優先，生成品質更穩定 |
| LLM 模型 | Breeze-2-8B（MediaTek Research） | 繁中優化、8B 可在消費級 GPU 執行、地端部署資料不外送 |
| 向量索引管理 | manifest mtime 版本比對 | 來源 JSON 有更動時啟動自動重建，無需手動觸發 |
| 服務框架 | FastAPI + WebSocket | 非同步處理多連線；WebSocket 做語音串流、HTTP 做單次意見產製，職責分明 |

---

## 架構

```
┌─────────────────────────────────────────────────────┐
│  ltcfeWebDemo/          前端（靜態 HTML）            │
│  ├── index.html         評鑑委員操作主頁面           │
│  └── assets/
│      ├── javascripts/committee-script.js  核心邏輯  │
│      └── stylesheets/                               │
└───────────────────────┬─────────────────────────────┘
                        │ WebSocket  ws://…/api/stream
                        │ HTTP POST  /api/report
┌───────────────────────▼─────────────────────────────┐
│  api/                   後端（FastAPI）              │
│  ├── app/main.py             入口、CORS、lifespan    │
│  ├── app/routes.py           WebSocket + HTTP       │
│  ├── app/audio_processor.py  PCM16 VAD 緩衝器       │
│  ├── app/whisper_client.py   whisper.cpp HTTP client│
│  ├── app/llm_client.py       兩階段 LLM 評鑑意見    │
│  ├── app/data_preprocessor.py 資料預處理（離線）    │
│  ├── app/config.py           環境變數（BaseSettings）│
│  └── data/
│      ├── indicators.json     評鑑指標索引（898 條） │
│      └── fewshot.json        歷年委員意見索引（1578 筆）│
└────────────┬────────────────────┬───────────────────┘
             │                    │
    ┌────────▼────────┐  ┌────────▼────────┐
    │  faster-whisper │  │  whisper.cpp    │
    │  (CPU/CUDA)     │  │  (Vulkan GPU)   │
    └─────────────────┘  └─────────────────┘
                    ┌────────▼────────┐
                    │  LLM (vLLM)     │
                    │  Breeze-2-8B    │
                    │  HTTP :8001     │
                    └─────────────────┘
```

---

## 快速啟動（Demo）

### 需求

- **NVIDIA GPU（VRAM ≥ 16 GB）** — 跑 Breeze-2-8B 的最低門檻
- Docker + Docker Compose
- nvidia-container-toolkit（讓 Docker 能用 GPU）
- 網路（首次 build image 要下載模型約 18 GB）

> 沒 GPU 的話 `llm` 服務會起不來（8B 模型 CPU 跑不動）；若只想 demo 語音辨識，可先 `docker compose up api web`，跳過 llm。

### 1. 複製設定

```bash
cp .env.example .env
# 預設值可直接用，不需要改
```

### 2. Build + 啟動服務

```bash
docker compose up -d --build
```

- **首次 build 約 30–60 分鐘**（下載 Whisper 1.5 GB + LLM 16 GB + Embedding 470 MB，模型會 bake 進 image）
- **首次啟動後約 1–3 分鐘**（vLLM 載入模型到 GPU）

檢查服務就緒：
```bash
curl http://localhost:8000/api/health
# {"status":"ok","backend":"faster-whisper","model":"phate334/Breeze-ASR-25-ct2"}
```

### 3. 開啟前端

用瀏覽器開啟 <http://localhost:8081>（Nginx 容器提供）。

頁面頂部輸入 `ws://localhost:8000/api/stream` → 點「連線」即可開始 demo。

### 停止 / 清除

```bash
docker compose down          # 停止服務，保留 image
docker compose down --rmi all # 連 image 一起刪（釋放 ~20GB）
```

---

## 服務端口

| 服務 | 端口 | 說明 |
|------|------|------|
| api | 8000 | FastAPI 後端（WebSocket + HTTP） |
| llm | 8001 | vLLM 推論服務 |
| web | 8081 | 靜態前端（Nginx，選用） |

---

## 環境變數

完整清單見 `.env.example`。常用設定：

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `STREAM_MODEL` | `phate334/Breeze-ASR-25-ct2` | faster-whisper 模型 |
| `DEVICE` | `auto` | `auto` / `cpu` / `cuda` |
| `COMPUTE_TYPE` | `int8` | `int8` / `float16` / `float32` |
| `WHISPER_CPP_URL` | （空） | 設定後改用 whisper.cpp |
| `LLM_BASE_URL` | `http://llm:8001/v1` | vLLM 服務位址 |
| `LLM_MODEL` | `MediaTek-Research/Breeze-2-8B-Instruct` | LLM 模型名稱 |
| `CORS_ORIGINS` | `*` | 允許的 CORS 來源，production 請改為具體網域 |

---

## 轉錄後端切換

**faster-whisper（預設）**
- 支援 CPU 與 CUDA，不需額外設定
- 模型在 Docker build 時預載進 image

**whisper.cpp（Vulkan GPU 加速）**
- 需自行啟動 whisper.cpp server
- 設定 `WHISPER_CPP_URL=http://<host>:8080/inference`
- 設定後優先使用，faster-whisper 自動停用

---

## 前端操作流程

1. 開啟頁面，輸入 WebSocket 位址 → 點「連線」
2. 展開評鑑題目（如 A1 業務計畫...）
3. 點「備忘錄」麥克風 → 對著麥克風說出現場觀察紀錄
4. 點「主要意見」麥克風 → 補充重點意見
5. 點「AI產製」→ LLM 自動整理成條列式評量意見填入欄位
6. 視需要手動調整 AI 產製的內容

---

## 本地開發（不用 Docker）

```bash
cd api
pip install -r requirements.txt

# 首次執行：將 Excel/docx 原始資料轉為 JSON 索引
python3 -m app.data_preprocessor
# 產出 api/data/indicators.json、api/data/fewshot.json

# 啟動後端
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 專案結構

```
whisper/
├── api/                              後端
│   ├── app/
│   │   ├── main.py                   FastAPI 入口
│   │   ├── routes.py                 WebSocket /api/stream + POST /api/report
│   │   ├── audio_processor.py        PCM16 幀緩衝 + RMS 能量 VAD
│   │   ├── whisper_client.py         whisper.cpp HTTP client
│   │   ├── llm_client.py             LLM 評鑑意見產製（指標查詢 + few-shot）
│   │   ├── data_preprocessor.py      Excel/docx → JSON 索引（離線執行）
│   │   └── config.py                 pydantic BaseSettings
│   ├── data/
│   │   ├── indicators.json           評鑑指標索引（898 條，112~115年）
│   │   └── fewshot.json              歷年委員意見索引（1578 筆，60 個代碼）
│   ├── Dockerfile
│   └── requirements.txt
├── ltcfeWebDemo/                     前端
│   ├── index.html                    主頁面（Bootstrap 5 + Font Awesome）
│   └── assets/
│       ├── javascripts/
│       │   ├── committee-script.js   核心 JS（WS + AudioWorklet + AI產製）
│       │   └── vendor/
│       └── stylesheets/
├── docs/
│   ├── technical-guide.md            技術選型與概念教學
│   └── frontend-api.md               前端對接 API 文件
├── k8s/                              Kubernetes 部署設定
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 相關文件

- [技術選型與概念教學](docs/technical-guide.md)
- [前端對接 API 文件](docs/frontend-api.md)
