# Whisper 即時語音轉文字服務

瀏覽器麥克風即時串流轉錄，基於 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)。

> **分支說明**：`main` 為生產配置（Breeze ASR 25 + GPU），`local` 為本機測試配置（base 模型 + CPU）

---

## 架構

```
瀏覽器（麥克風 + 前端 VAD）
    │
    ▼
┌──────────────────────────────┐
│  Nginx (web container)       │
│  /        前端頁面            │
│  /api/*   反向代理 → api      │
└──────────────────────────────┘
    │ WebSocket（偵測語音停頓後送出片段）
    ▼
┌──────────────────────────────┐
│  FastAPI (api container)     │
│                              │
│  WS /api/stream  即時轉錄    │
│  GET /api/health 健康檢查    │
│  GET /api/config VAD 參數    │
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
| 通訊 | WebSocket + 前端 VAD（語音斷點自動切段） |
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

# 1. GPU Node 加 label（只需做一次）
#    叢集裡有些機器有 GPU、有些沒有，K8s 不知道哪台有
#    你要自己貼標籤告訴它，Pod 才會排到正確的機器上
#
#    先看有哪些 Node：
kubectl get nodes
#    幫有 GPU 的機器貼 gpu=true 標籤：
kubectl label node <你的GPU機器名稱> gpu=true
#    例如：
#      kubectl label node gpu-server-01 gpu=true
#      kubectl label node gpu-server-02 gpu=true

# 2. 修改設定
#    k8s/pv.yaml     → NFS Server IP 和路徑
#    k8s/ingress.yaml → 你的 domain

# 3. Build image（在每台 Node 上，或用 registry）
docker build -t whisper-service:latest -f api/Dockerfile .

# 4. 部署
kubectl apply -k k8s/

# 5. 確認
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
| `MAX_CONNECTIONS` | `20` | 最大同時連線數 |
| `CORS_ORIGINS` | `*` | 允許的 CORS origin（逗號分隔） |
| `DEFAULT_LANGUAGE` | `zh` | 預設辨識語言（zh/en/auto） |
| `VAD_SILENCE_THRESHOLD` | `0.015` | 前端 VAD 靜音判定閾值（RMS） |
| `VAD_SILENCE_DURATION_MS` | `800` | 靜音超過此毫秒數才切段 |
| `VAD_MIN_SPEECH_MS` | `500` | 最短語音長度（過短丟棄） |
| `VAD_MAX_CHUNK_MS` | `10000` | 最長片段（強制切段） |

---

## API

### WebSocket 即時轉錄

```
WS /api/stream

→ {"action": "start", "language": "zh"}   開始
→ {"action": "stop"}                       停止
→ (binary) 音訊片段                        VAD 偵測停頓後送出

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
│   ├── Dockerfile          # Nginx 前端 image
│   ├── nginx.conf          # 反向代理設定
│   └── index.html          # 前端頁面
├── k8s/
│   ├── kustomization.yaml  # kubectl apply -k k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── pv.yaml             # NFS (main) / local-path (local)
│   ├── pvc.yaml
│   ├── deployment.yaml     # API: GPU (main) / CPU (local)
│   ├── service.yaml        # API Service
│   ├── web-deployment.yaml # 前端 Nginx
│   ├── web-service.yaml    # 前端 Service
│   └── ingress.yaml        # 路由分流（/api → api, / → web）
├── .github/workflows/
│   └── docker-build.yml
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 切換模型（K8s）

```bash
# 1. 修改 ConfigMap 裡的模型名稱
kubectl edit configmap whisper-config -n whisper
# 把 STREAM_MODEL 改成你要的模型，例如：
#   base / small / large-v2 / phate334/Breeze-ASR-25-ct2

# 2. 重啟 Pod（模型會重新載入）
kubectl rollout restart deployment/api -n whisper

# 3. 等待新 Pod Ready（首次使用新模型會自動下載）
kubectl get pods -n whisper -w
```

不需要重建 image，不需要改程式碼。

---

## 停止服務

```bash
# Docker Compose
docker compose down

# K8s
kubectl delete -k k8s/
```
