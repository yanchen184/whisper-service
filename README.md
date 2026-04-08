# Whisper 即時語音轉文字服務

瀏覽器麥克風即時串流轉錄，基於 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)。

> **分支說明**：`main` 為生產配置（Breeze ASR 25 + GPU），`local` 為本機測試配置（base 模型 + CPU）

---

## 架構

```
瀏覽器（麥克風）
    │ WebSocket（每 5 秒送一段音訊）
    ▼
┌──────────────────────────────┐
│  FastAPI (api container)     │
│                              │
│  WS /api/stream  即時轉錄    │
│  GET /api/health 健康檢查    │
│  /               前端頁面    │
│                              │
│  faster-whisper (GPU/CPU)    │
│  ffmpeg pipe (webm → wav)    │
└──────────────────────────────┘
    │
    ▼
  PVC: model-cache（模型快取）
```

## 技術棧

| 層級 | 技術 |
|------|------|
| 前端 | HTML / CSS / JavaScript（單頁） |
| 通訊 | WebSocket（瀏覽器麥克風 → 後端） |
| 後端 | Python 3.11 + FastAPI |
| 轉錄引擎 | faster-whisper（CTranslate2） |
| 音訊處理 | ffmpeg pipe 模式（webm → 16kHz wav） |
| 容器 | Docker |
| 部署 | K8s + Kustomize |

---

## 快速開始

### Docker Compose（本機）

```bash
git clone https://github.com/yanchen184/whisper-service.git
cd whisper-service
git checkout local  # 本機測試用 local 分支

cp .env.example .env
docker compose up -d

open http://localhost:8000
```

### K8s 部署（生產）

```bash
git clone https://github.com/yanchen184/whisper-service.git
cd whisper-service

# Build image
docker build -t whisper-service:latest -f api/Dockerfile .

# 部署（修改 k8s/pv.yaml 的 NFS IP 和路徑後）
kubectl apply -k k8s/

# 確認
kubectl get pods -n whisper
kubectl port-forward -n whisper svc/api 8000:80
open http://localhost:8000
```

---

## 硬體需求

### 本機測試（local 分支，base 模型）

| 項目 | 最低 |
|------|------|
| CPU | 4 核 |
| RAM | 8 GB |
| GPU | 不需要 |

### 生產環境（main 分支，Breeze ASR 25，10 人同時使用）

| 項目 | 規格 | 數量 | 用途 |
|------|------|------|------|
| GPU Node | 8 vCPU, 32GB RAM, NVIDIA L4 24GB | 2 台 | API Pod x2（即時轉錄） |
| 磁碟 | NFS 或 local-path | — | model-cache 10Gi |

### 模型 VRAM 需求

| 模型 | VRAM (FP16) | 適合場景 |
|------|-------------|---------|
| base | 0.7 GB | 本機測試 |
| small | 1 GB | 日常使用 |
| large-v2 | 5 GB | 英文技術術語 |
| Breeze ASR 25 | 5 GB | 台灣華語、中英混用（預設） |

---

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `STREAM_MODEL` | `phate334/Breeze-ASR-25-ct2` | 模型（main）/ `base`（local） |
| `DEVICE` | `auto` | `auto` / `cuda` / `cpu` |
| `COMPUTE_TYPE` | `int8` | `int8`(CPU) / `float16`(GPU) |
| `MAX_CONNECTIONS` | `5` | 最大同時連線數 |
| `CORS_ORIGINS` | `*` | 允許的 CORS origin（逗號分隔） |

---

## API

### WebSocket 即時轉錄

```
WS /api/stream

→ {"action": "start", "language": "zh"}   開始
→ {"action": "stop"}                       停止
→ (binary) 音訊片段                        每 5 秒

← {"type": "status", "message": "started"}
← {"type": "transcript", "text": "..."}
← {"type": "error", "message": "..."}
```

### 健康檢查

```bash
curl http://localhost:8000/api/health
# {"status": "ok", "model": "base"}
# 模型載入中回 503: {"status": "loading"}
```

---

## 專案結構

```
whisper-service/
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── config.py       # 環境變數
│       ├── main.py         # FastAPI + 模型預載
│       └── routes.py       # WebSocket 即時轉錄 + /health
├── web/
│   └── index.html          # 前端
├── k8s/
│   ├── kustomization.yaml  # kubectl apply -k k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── pv.yaml             # NFS (main) / local-path (local)
│   ├── pvc.yaml
│   ├── deployment.yaml     # GPU (main) / CPU (local)
│   ├── service.yaml
│   └── ingress.yaml
├── .github/workflows/
│   └── docker-build.yml
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 停止服務

```bash
# Docker Compose
docker compose down

# K8s
kubectl delete -k k8s/
```
