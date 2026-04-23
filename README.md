# Whisper 即時語音轉文字 + LLM 報告服務

瀏覽器麥克風即時串流轉錄，基於 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)。
轉錄後可一鍵送 LLM 產生結構化報告（潤飾 → 分類 → 套模板）。

---

## 硬體需求

### 本機測試（local 分支，base 模型 + 小 LLM）

| 項目 | 最低 |
|------|------|
| CPU | 4 核 |
| RAM | 8 GB |
| GPU | 不需要 |
| 磁碟 | 5 GB（模型已 bake 進 image） |

### 生產環境（main 分支，Breeze ASR 25 + Breeze 2 8B，10 人同時使用）

| 項目 | 規格 | 數量 | 說明 |
|------|------|------|------|
| GPU Node | 8 vCPU, 32GB RAM, NVIDIA L4 24GB | 2 台 | 每台跑 API + LLM Pod，共用 GPU |
| 磁碟 | SSD 100GB | 每台 | 模型已 bake 進 image，不需要 NFS |

**地端自建參考（每台 Node）**：

| 項目 | 最低規格（local 分支） | 生產規格（main 分支） |
|------|----------------------|---------------------|
| CPU | 4 核 | 8 核以上（Intel Xeon / AMD EPYC） |
| RAM | 8 GB | 32 GB |
| GPU | 不需要 | NVIDIA L4 24GB 或 T4 16GB 或 RTX 4090 24GB |
| 磁碟 | SSD 50GB | SSD 100GB |
| OS | Ubuntu 22.04 | Ubuntu 22.04 + NVIDIA Driver 535+ + CUDA 12.x |
| K8s | K3s / Docker Desktop K8s | K8s + NVIDIA GPU Operator |

### 使用模型

**Whisper — Breeze ASR 25**（MediaTek Research，基於 Whisper large-v2）
- VRAM：5 GB（FP16）
- 磁碟：~3 GB（已 bake 進 image）
- 強項：台灣華語、中英混用，WER 比原版 large-v2 改善 56%

**LLM — Breeze 2 8B Instruct**（MediaTek Research，基於 Llama 3.2）
- VRAM：~6 GB（FP16，gpu-memory-utilization 0.4）
- 磁碟：~16 GB（已 bake 進 image）
- 強項：繁體中文 Instruct 微調，支援 function calling

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
│  POST /api/report LLM 報告   │
│  GET /api/health 健康檢查    │
│  GET /api/config VAD 參數    │
│                              │
│  faster-whisper (GPU/CPU)    │
│  ffmpeg pipe (webm → wav)    │
└──────────────────────────────┘
    │ POST /v1/chat/completions
    ▼
┌──────────────────────────────┐
│  vLLM (llm container)        │
│                              │
│  OpenAI 相容 API :8001       │
│  Breeze 2 8B Instruct        │
│  潤飾 → Tag 分類 → 套模板     │
└──────────────────────────────┘
```

### 使用者操作流程

```
1. 對著麥克風說話 → 文字即時出現
2. 手動編輯/修正轉錄文字
3. 按「產生報告」→ LLM 自動潤飾、分類、套模板
4. 查看結構化報告
```

## 技術棧

| 層級 | 技術 |
|------|------|
| 前端 | HTML / CSS / JavaScript（單頁） |
| 通訊 | WebSocket + 前端 VAD（語音斷點自動切段） |
| 後端 | Python 3.11 + FastAPI |
| 轉錄引擎 | faster-whisper（CTranslate2） |
| LLM 推理 | vLLM（OpenAI 相容 API） |
| 音訊處理 | ffmpeg pipe 模式（webm → 16kHz wav） |
| 容器 | Docker |
| 部署 | K8s + Kustomize |

---

## 部署方式（斷網環境）

所有模型已 bake 進 Docker image，**部署不需要網路**。

### Image 準備（有網路的機器）

```bash
git clone https://github.com/yanchen184/whisper-service.git
cd whisper-service

# Build 三個 image（模型會在 build 時下載並打包進 image）
docker build -t whisper-api:latest -f api/Dockerfile \
  --build-arg WHISPER_MODEL=phate334/Breeze-ASR-25-ct2 .
docker build -t whisper-web:latest -f web/Dockerfile web/
docker build -t whisper-llm:latest -f llm/Dockerfile \
  --build-arg LLM_MODEL=MediaTek-Research/Breeze-2-8B-Instruct .

# 匯出 image
docker save whisper-api:latest | gzip > whisper-api.tar.gz
docker save whisper-web:latest | gzip > whisper-web.tar.gz
docker save whisper-llm:latest | gzip > whisper-llm.tar.gz
```

### 搬運到地端

```bash
# 用 USB / 內網搬運 .tar.gz 到地端機器

# 匯入 image
docker load < whisper-api.tar.gz
docker load < whisper-web.tar.gz
docker load < whisper-llm.tar.gz
```

---

## K8s 部署（生產）

```bash
# 1. GPU Node 加 label（只需做一次）
kubectl get nodes
kubectl label node <你的GPU機器名稱> gpu=true

# 2. 匯入 image 到每台 Node（或用 registry）
#    方法 A：每台 Node 都 docker load
#    方法 B：推到 registry，修改 deployment image 和 imagePullPolicy

# 3. 部署
kubectl apply -k k8s/

# 4. 確認
kubectl get pods -n whisper
kubectl port-forward -n whisper svc/web 8080:80
open http://localhost:8080
```

---

## K8s YAML 說明

| 檔案 | 用途 | 維運需修改 |
|------|------|-----------|
| `namespace.yaml` | 建立 `whisper` namespace | 不需要 |
| `configmap.yaml` | 所有環境變數（模型、VAD、LLM 參數） | **調整參數時改這裡** |
| `deployment.yaml` | API Pod（faster-whisper 轉錄） | **改 image 名稱、調整 replicas 和資源** |
| `service.yaml` | API Service | 不需要 |
| `web-deployment.yaml` | 前端 Nginx Pod | **改 image 名稱** |
| `web-service.yaml` | 前端 Service | 不需要 |
| `llm-deployment.yaml` | LLM Pod（vLLM 推理） | **改 image 名稱、調整資源** |
| `llm-service.yaml` | LLM Service | 不需要 |
| `ingress.yaml` | 外部入口 | **改 domain、TLS 設定** |
| `kustomization.yaml` | Kustomize 入口 | 不需要 |

---

## 常見維運操作

```bash
# 查看 Pod 狀態
kubectl get pods -n whisper

# 查看 API 日誌
kubectl logs -n whisper deployment/api -f

# 查看 LLM 日誌
kubectl logs -n whisper deployment/llm -f

# 查看前端日誌
kubectl logs -n whisper deployment/web -f

# 擴縮容
kubectl scale deployment/api -n whisper --replicas=3
kubectl scale deployment/llm -n whisper --replicas=2

# 重啟（rolling update）
kubectl rollout restart deployment/api -n whisper
kubectl rollout restart deployment/llm -n whisper
kubectl rollout restart deployment/web -n whisper

# 確認 ConfigMap 內容
kubectl get configmap whisper-config -n whisper -o yaml
```

### 故障排除

| 狀況 | 檢查方式 | 可能原因 |
|------|---------|---------|
| Pod `CrashLoopBackOff` | `kubectl logs -n whisper <pod-name>` | 記憶體不足（OOM）、GPU 不可用 |
| Pod `Pending` | `kubectl describe pod -n whisper <pod-name>` | Node 資源不足、GPU label 未設定 |
| 前端打不開 | `kubectl get svc,ingress -n whisper` | Ingress 設定錯誤、web Pod 未 Running |
| 轉錄沒反應 | `curl <host>/api/health` | API 回 503 表示模型還在載入 |
| 產生報告失敗 | `curl <host>/api/health`、查 LLM 日誌 | LLM Pod 未 Ready、VRAM 不足 |
| WebSocket 斷線 | 檢查 Ingress timeout 設定 | nginx Ingress 預設 60s timeout，需調大 |

### 停止服務

```bash
kubectl delete -k k8s/

# Docker Compose
docker compose down
```

---

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `STREAM_MODEL` | `phate334/Breeze-ASR-25-ct2` | Whisper 模型 |
| `DEVICE` | `auto` | `auto` / `cuda` / `cpu` |
| `COMPUTE_TYPE` | `int8` | `int8`(CPU) / `float16`(GPU) |
| `MAX_CONNECTIONS` | `20` | 最大同時連線數 |
| `CORS_ORIGINS` | `*` | 允許的 CORS origin |
| `DEFAULT_LANGUAGE` | `zh` | 預設辨識語言（zh/en/auto） |
| `VAD_SILENCE_THRESHOLD` | `0.015` | 前端 VAD 靜音判定閾值（RMS） |
| `VAD_SILENCE_DURATION_MS` | `800` | 靜音超過此毫秒數才切段 |
| `VAD_MIN_SPEECH_MS` | `500` | 最短語音長度（過短丟棄） |
| `VAD_MAX_CHUNK_MS` | `10000` | 最長片段（強制切段） |
| `LLM_BASE_URL` | `http://llm:8001/v1` | vLLM API 位址 |
| `LLM_MODEL` | `MediaTek-Research/Breeze-2-8B-Instruct` | LLM 模型名稱 |
| `LLM_MAX_TOKENS` | `2048` | LLM 最大生成 token 數 |
| `LLM_TEMPERATURE` | `0.3` | LLM 溫度（越低越穩定） |

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

### LLM 報告生成

```
POST /api/report
Content-Type: application/json

→ {"transcript": "今天跟王先生開會，他說預算大概三百萬..."}

← {
    "tag": "meeting",
    "polished": "今天與王先生開會，他表示預算約新台幣 300 萬元...",
    "structured": {
      "title": "客戶預算討論會議",
      "date": null,
      "participants": ["王先生"],
      "summary": "討論專案預算與交付時程",
      "action_items": ["確認第一版交付日期"],
      "decisions": ["預算暫定 300 萬"]
    }
  }
```

### 健康檢查

```bash
curl http://<host>/api/health
# {"status": "ok", "model": "phate334/Breeze-ASR-25-ct2"}
# 模型載入中回 503: {"status": "loading"}
```

---

## 本機開發

### Docker Compose

```bash
git clone https://github.com/yanchen184/whisper-service.git
cd whisper-service
git checkout local  # 本機測試用 local 分支

cp .env.example .env   # 預設值即可
docker compose up -d

# 首次 build 會下載模型，需等待
open http://localhost:8081
```

### 本機 K8s 測試（Docker Desktop）

> Docker Desktop 內建 K8s，image 與本機 Docker 共用，不需另外匯入

```bash
git checkout local

# 1. 啟用 K8s
#    Docker Desktop → Settings → Kubernetes → Enable Kubernetes → Apply & Restart

# 2. 確認 kubectl 指向 Docker Desktop
kubectl config use-context docker-desktop

# 3. Build image
docker build -t whisper-api:latest -f api/Dockerfile .
docker build -t whisper-web:latest -f web/Dockerfile web/
docker build -t whisper-llm:latest -f llm/Dockerfile llm/

# 4. 部署
kubectl apply -k k8s/

# 5. 確認 Pod Running
kubectl get pods -n whisper -w

# 6. 測試
kubectl port-forward -n whisper svc/web 8080:80
open http://localhost:8080
```

### 本機 K8s 測試（k3d）

> k3d 有獨立 image 空間，需要 `k3d image import`

```bash
git checkout local

# 安裝 k3d
brew install k3d

# 建立叢集
k3d cluster create whisper

# Build image 並匯入 k3d
docker build -t whisper-api:latest -f api/Dockerfile .
docker build -t whisper-web:latest -f web/Dockerfile web/
docker build -t whisper-llm:latest -f llm/Dockerfile llm/
k3d image import whisper-api:latest whisper-web:latest whisper-llm:latest -c whisper

# 部署
kubectl apply -k k8s/

# 確認 Pod Running
kubectl get pods -n whisper -w

# 測試
kubectl port-forward -n whisper svc/web 8080:80
open http://localhost:8080
```

---

## 專案結構

```
whisper-service/
├── api/
│   ├── Dockerfile          # Whisper API image（模型 bake 進 image）
│   ├── requirements.txt
│   └── app/
│       ├── config.py       # 環境變數（Whisper + LLM）
│       ├── main.py         # FastAPI + 模型預載
│       ├── routes.py       # WebSocket 轉錄 + POST /api/report
│       └── llm_client.py   # LLM 呼叫邏輯 + Prompt 模板
├── llm/
│   └── Dockerfile          # vLLM image（LLM 模型 bake 進 image）
├── web/
│   ├── Dockerfile          # Nginx 前端 image
│   ├── nginx.conf          # 反向代理設定
│   └── index.html          # 前端頁面（轉錄 + 報告）
├── k8s/
│   ├── kustomization.yaml  # kubectl apply -k k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml      # 所有環境變數
│   ├── deployment.yaml     # API Pod
│   ├── service.yaml        # API Service
│   ├── llm-deployment.yaml # LLM Pod
│   ├── llm-service.yaml    # LLM Service
│   ├── web-deployment.yaml # 前端 Nginx
│   ├── web-service.yaml    # 前端 Service
│   └── ingress.yaml        # 路由分流
├── .github/workflows/
│   └── docker-build.yml
├── docker-compose.yml
├── .env.example
└── README.md
```

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
