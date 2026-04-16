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

## 快速啟動

### 需求

- Docker + Docker Compose
- （GPU 加速）NVIDIA GPU + nvidia-container-toolkit

### 1. 複製設定

```bash
cp .env.example .env
# 依需求修改 .env
```

### 2. 啟動服務

```bash
docker compose up -d
```

> `api/data/` 透過 volume 掛載進 container，需確認 `indicators.json` 與 `fewshot.json` 已存在。
> 首次執行請見「本地開發」章節的資料預處理步驟。

### 3. 開啟前端

用瀏覽器開啟 `ltcfeWebDemo/index.html`，或透過靜態伺服器：

```bash
npx serve ltcfeWebDemo
```

頁面頂部輸入 `ws://localhost:8000/api/stream` → 點「連線」。

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

---

## 分支差異（僅規格不同，程式碼完全一致）

> **維護策略**：以 `main` 為唯一維護分支；`local` 已凍結為歷史快照，不再更新。本機測試請直接使用 `main`，依 Docker Compose 區段以環境變數覆寫 `STREAM_MODEL` 即可切為 `base` 模型。
>
> `main` 為生產配置（GPU），`local` 為本機測試配置（CPU）

| 檔案 | 設定 | local | main |
|------|------|-------|------|
| `configmap.yaml` | STREAM_MODEL | `base` | `phate334/Breeze-ASR-25-ct2` |
| | LLM_MODEL | `MediaTek-Research/Breeze-2-8B-Instruct` | `MediaTek-Research/Breeze-2-8B-Instruct` |
| | DEVICE | `cpu` | `cuda` |
| | COMPUTE_TYPE | `int8` | `float16` |
| `deployment.yaml` | replicas | 1 | 2 |
| | CPU request / limit | 500m / 2 | 4 / 8 |
| | Memory request / limit | 512Mi / 2Gi | 8Gi / 16Gi |
| | GPU | 無 | `nvidia.com/gpu: 1` |
| | nodeSelector | 無 | `gpu: "true"` |
| `llm-deployment.yaml` | replicas | 1 | 1 |
| | GPU | 無 | `nvidia.com/gpu: 1` |
| | vLLM args | `--dtype float32` | `--dtype half --gpu-memory-utilization 0.4` |
| `ingress.yaml` | ingressClass | 無（Traefik） | nginx + WebSocket timeout |
| | host | 無 | `whisper.example.com` |
| `docker-compose.yml` | STREAM_MODEL 預設 | `base` | `phate334/Breeze-ASR-25-ct2` |
