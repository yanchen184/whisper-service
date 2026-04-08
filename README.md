# Whisper 語音轉文字服務

即時語音轉文字 + 批次檔案轉錄服務，基於 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 引擎，支援中英混用。

---

## 技術架構

```
                        ┌─────────────────────────────────┐
                        │          瀏覽器 Client           │
                        │  ┌───────────┐  ┌────────────┐  │
                        │  │ 即時轉錄   │  │ 檔案轉錄   │  │
                        │  │ (麥克風)   │  │ (上傳檔案) │  │
                        │  └─────┬─────┘  └─────┬──────┘  │
                        └───────┼───────────────┼─────────┘
                         WebSocket            HTTP POST
                                │               │
┌───────────────────────────────┼───────────────┼──────────┐
│                        Ingress / Port 8000               │
│  ┌───────────────────────────────────────────────────┐   │
│  │              FastAPI (api container)               │   │
│  │                                                   │   │
│  │  WS /api/stream     即時轉錄（收音訊→轉錄→回傳）  │   │
│  │  POST /api/transcribe  上傳→排隊                   │   │
│  │  GET  /api/tasks/{id}  查詢狀態                    │   │
│  │  GET  /api/models      模型列表                    │   │
│  │  /                     前端靜態頁面                │   │
│  └──────────────────────┬────────────────────────────┘   │
│                         │                                │
│              ┌──────────┼──────────┐                     │
│              ▼                     ▼                     │
│  ┌───────────────┐     ┌──────────────────┐              │
│  │     Redis     │     │  Worker          │              │
│  │  (任務佇列)   │────►│  (批次轉錄)     │              │
│  │               │     │  faster-whisper  │              │
│  └───────────────┘     └──────────────────┘              │
│                                                          │
│  Volumes:                                                │
│    model-cache  → /root/.cache/huggingface (模型快取)    │
│    upload-data  → /data (上傳檔案 + 轉錄結果)           │
│    redis-data   → /data (Redis 持久化)                   │
└──────────────────────────────────────────────────────────┘
```

## 技術棧

| 層級 | 技術 | 說明 |
|------|------|------|
| **前端** | HTML / CSS / JavaScript | 單頁應用，內嵌即時轉錄 + 方案報告 |
| **API** | Python 3.11 + FastAPI | REST API + WebSocket，async |
| **即時轉錄** | WebSocket + MediaRecorder | 瀏覽器麥克風 → 每 5 秒送音訊片段 → 即時回傳文字 |
| **批次轉錄** | arq + Redis | 非同步任務佇列，上傳後排隊處理 |
| **轉錄引擎** | faster-whisper (CTranslate2) | 比原版 Whisper 快 4-8x，VRAM 省 50-70% |
| **音訊處理** | ffmpeg | webm/mp4 → 16kHz mono wav 自動轉換 |
| **容器化** | Docker / Docker Compose | 本機一鍵啟動 |
| **部署** | Kubernetes + Kustomize | 生產環境部署 |
| **CI/CD** | GitHub Actions | push 自動 build Docker image |

---

## 硬體需求

### 本機開發 / Demo

| 項目 | 最低 | 建議 |
|------|------|------|
| CPU | 4 核 | 8 核 |
| RAM | 8 GB | 16 GB |
| GPU | 不需要（CPU 可跑） | NVIDIA GPU（大幅加速） |
| 磁碟 | 5 GB | 10 GB |
| 可用模型 | tiny, base, small | + medium |

### 生產環境（K8s）

#### 最低配置（3-5 人同時使用，base 模型）

| Node | 規格 | 數量 | 用途 |
|------|------|------|------|
| GPU Node | 8 vCPU, 32GB RAM, **NVIDIA T4 16GB** | 1 | API + 即時轉錄 + 批次轉錄 |
| CPU Node | 4 vCPU, 16GB RAM | 1 | Redis, Ingress |

#### 建議配置（10 人同時使用，Breeze ASR 25）

| Node | 規格 | 數量 | 用途 |
|------|------|------|------|
| GPU Node | 8 vCPU, 32GB RAM, **NVIDIA L4 24GB** | **2-3** | API x2 + Worker x1 |
| CPU Node | 4 vCPU, 16GB RAM | 1 | Redis, Ingress |

> Breeze ASR 25 (1.54B) 單模型佔 ~5GB VRAM。每張 L4 (24GB) 可跑一個 Pod，同時服務 3-5 人即時轉錄。10 人需要 2-3 張 GPU。

#### 各模型 GPU VRAM 需求

| 模型 | 參數量 | VRAM (FP16) | VRAM (INT8) | 適合場景 |
|------|--------|-------------|-------------|---------|
| tiny | 39M | 0.5 GB | 0.3 GB | 快速測試 |
| base | 74M | 0.7 GB | 0.4 GB | 一般用途（預設） |
| small | 244M | 1 GB | 0.6 GB | 日常使用 |
| medium | 769M | 2.5 GB | 1.5 GB | 會議記錄 |
| large-v2 | 1.55B | 5 GB | 3 GB | 技術內容、英文術語 |
| large-v3-turbo | 809M | 3 GB | 1.8 GB | 精度與速度兼顧 |
| Breeze ASR 25 | 1.54B | 5 GB | 3 GB | 台灣華語、中英混用 |

---

## 模型選擇指南

| 場景 | 推薦模型 | 理由 |
|------|---------|------|
| 快速 Demo | base | 小（142MB）、速度快 |
| 一般中文會議 | small / medium | 品質與速度平衡 |
| 英文技術術語（K8s, Docker 等） | **large-v2** | 英文術語辨識最佳 |
| 台灣華語 + 中英混用 | **Breeze ASR 25** | 中英 code-switch WER 改善 56% |
| 最高精度（不計速度） | large-v3 | WER 最低，但有幻覺風險 |
| 精度與速度兼顧 | large-v3-turbo | 比 large 快 8 倍，精度接近 |

> 詳細模型比較與實測數據見 [MODEL_COMPARISON.md](MODEL_COMPARISON.md)

---

## 快速開始

### 方式一：Docker Compose（本機）

```bash
# 1. Clone
git clone https://github.com/yanchen184/whisper-service.git
cd whisper-service

# 2. 啟動
docker compose up -d

# 3. 開瀏覽器
open http://localhost:8000
```

首次啟動會自動下載模型（預設 base，142MB），之後快取不重複下載。

#### 啟用 GPU

```bash
# 1. 取消 docker-compose.yml 中 worker 的 GPU 註解
# 2. 修改 .env
DEVICE=cuda
COMPUTE_TYPE=float16

# 3. 重啟
docker compose up -d
```

### 方式二：K8s 部署（生產）

```bash
# 1. 在 K8s node 上 build image
git clone https://github.com/yanchen184/whisper-service.git
cd whisper-service
docker build -t whisper-service:latest ./api

# 2. 一鍵部署
kubectl apply -k k8s/

# 3. 確認 Pod 狀態
kubectl get pods -n whisper

# 4. 修改 ingress.yaml 的 host 為你的 domain
```

---

## 專案結構

```
whisper-service/
├── api/                          # 後端
│   ├── Dockerfile                # Docker 映像定義
│   ├── requirements.txt          # Python 依賴
│   └── app/
│       ├── main.py               # FastAPI 進入點 + 模型預載
│       ├── routes.py             # API 路由 + WebSocket 即時轉錄
│       ├── tasks.py              # 轉錄任務邏輯 + 模型清單
│       ├── worker.py             # arq Worker 設定
│       ├── storage.py            # 檔案儲存 + SRT 產生
│       ├── config.py             # 環境變數設定
│       └── models.py             # Pydantic schemas
│
├── web/
│   └── index.html                # 前端（即時轉錄 + 方案報告 + 系統架構）
│
├── k8s/                          # Kubernetes 部署檔
│   ├── kustomization.yaml        # 一鍵部署: kubectl apply -k k8s/
│   ├── namespace.yaml            # whisper namespace
│   ├── configmap.yaml            # 模型、語言、Redis 等設定
│   ├── secret.yaml               # 密碼
│   ├── redis.yaml                # Redis StatefulSet + PVC
│   ├── api-deployment.yaml       # API Deployment + GPU + Service
│   ├── worker-deployment.yaml    # Worker Deployment + GPU
│   └── ingress.yaml              # Ingress + WebSocket 支援
│
├── .github/workflows/
│   └── docker-build.yml          # CI: 自動 build image → ghcr.io
│
├── docker-compose.yml            # 本機 Docker Compose
├── .env                          # 環境變數（不入 git）
├── MODEL_COMPARISON.md           # 方案評估報告（含實測數據）
├── stream_server.py              # 獨立 WebSocket server（備用）
├── start-stream.sh               # 本機即時轉錄啟動腳本
├── run.sh                        # whisper.cpp CLI 腳本
└── transcribe.py                 # Python 版轉錄腳本（備用）
```

---

## API 文件

### 即時轉錄（WebSocket）

```
WS /api/stream

→ {"action": "start", "language": "zh"}     開始辨識
→ {"action": "stop"}                         停止辨識
→ (binary) 音訊片段                          每 5 秒自動送出

← {"type": "status", "message": "started"}  狀態通知
← {"type": "transcript", "text": "..."}     轉錄文字
```

### 批次轉錄（REST）

```bash
# 上傳音檔
curl -X POST http://localhost:8000/api/transcribe \
  -F "file=@audio.wav"
# → {"task_id": "xxx", "status": "queued"}

# 指定模型
curl -X POST "http://localhost:8000/api/transcribe?model=large-v2" \
  -F "file=@audio.wav"

# 查詢狀態
curl http://localhost:8000/api/tasks/{task_id}
# → {"status": "completed", "progress": 100, "result": {...}}

# 下載結果
curl http://localhost:8000/api/tasks/{task_id}/download?format=txt
curl http://localhost:8000/api/tasks/{task_id}/download?format=srt
curl http://localhost:8000/api/tasks/{task_id}/download?format=json

# 模型列表
curl http://localhost:8000/api/models
```

---

## K8s 部署細節

### Volume（PVC）

| PVC | 大小 | 用途 | 掛載到 |
|-----|------|------|--------|
| `model-cache` | 10Gi | 模型快取（自動下載，只下載一次） | API + Worker |
| `upload-data` | 50Gi | 上傳音檔 + 轉錄結果 | API + Worker |
| `redis-data` | 1Gi | Redis 持久化 | Redis |

### Pod 資源配置

| Pod | replicas | CPU | RAM | GPU | 用途 |
|-----|----------|-----|-----|-----|------|
| api | 2 | 4-8 核 | 8-16 GB | 1x L4 /pod | 即時轉錄 + REST API + 前端 |
| worker | 1 | 4-8 核 | 8-16 GB | 1x L4 /pod | 批次轉錄 |
| redis | 1 | 0.1-0.5 核 | 128-512 MB | 無 | 任務佇列 |

> 使用 Breeze ASR 25 時，每個 API/Worker Pod 需要一張獨立 GPU。10 人同時使用建議 API replicas: 2-3。

### Ingress 注意事項

WebSocket 需要特別設定 timeout，否則連線會被 nginx 斷掉：

```yaml
nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
nginx.ingress.kubernetes.io/proxy-body-size: "500m"
```

---

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `WHISPER_MODEL` | `base` | 批次轉錄預設模型 |
| `STREAM_MODEL` | `base` | 即時轉錄模型 |
| `DEVICE` | `auto` | `auto` / `cuda` / `cpu` |
| `COMPUTE_TYPE` | `int8` | `int8`(CPU) / `float16`(GPU) |
| `REDIS_URL` | `redis://redis:6379` | Redis 連線 |
| `UPLOAD_DIR` | `/data/uploads` | 上傳目錄 |
| `RESULT_DIR` | `/data/results` | 結果目錄 |

---

## 硬體申請清單（10 人同時使用 Breeze ASR 25）

| 項目 | 規格 | 數量 | 用途 |
|------|------|------|------|
| **GPU Node** | 8 vCPU, 32GB RAM, NVIDIA L4 24GB | **3 台** | API Pod x2（即時轉錄）+ Worker Pod x1（批次轉錄） |
| **CPU Node** | 4 vCPU, 16GB RAM | 1 台 | Redis, Ingress |
| **磁碟** | SSD | 自動配置 | model-cache 10Gi + upload-data 50Gi + redis-data 1Gi |

> 每張 L4 (24GB VRAM) 跑一個 Pod，Breeze ASR 25 佔 ~5GB VRAM（FP16），同時服務 3-5 人即時轉錄。

### 不同規模的配置

| 同時人數 | GPU | CPU Node | 月費（On-Demand） | 月費（Spot） |
|---------|-----|----------|------------------|-------------|
| 3-5 人 | T4 16GB x1 | 1 台 | ~$355 | **~$180** |
| 5-10 人 | L4 24GB x2 | 1 台 | ~$1,122 | **~$406** |
| **10 人** | **L4 24GB x3** | **1 台** | **~$1,633** | **~$559** |
| 10-20 人 | L4 24GB x4 | 2 台 | ~$2,244 | **~$812** |

### 與 OpenAI API 成本比較

| 方案 | 10 人每天各用 1hr | 10 人每天各用 4hr | 10 人每天各用 8hr |
|------|-----------------|-----------------|-----------------|
| **自建 L4 x3 Spot** | $559/月（固定） | $559/月（固定） | $559/月（固定） |
| OpenAI gpt-4o-transcribe | $108/月 | $432/月 | **$864/月** |
| OpenAI gpt-4o-mini | $54/月 | $216/月 | $432/月 |

> **損益平衡點**：10 人每天各用超過 ~5 小時，自建就比 OpenAI gpt-4o-transcribe 划算。
> 自建的優勢：資料不出站、無 API 呼叫上限、可自訂模型。

---

## 停止服務

```bash
# Docker Compose
docker compose down

# 清除所有資料（模型快取、上傳、結果）
docker compose down -v

# K8s
kubectl delete -k k8s/
```
