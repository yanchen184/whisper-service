# Whisper 即時語音轉文字服務

瀏覽器麥克風即時串流轉錄，基於 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)。

---

## 硬體需求

### 本機測試（local 分支，base 模型）

| 項目 | 最低 |
|------|------|
| CPU | 4 核 |
| RAM | 8 GB |
| GPU | 不需要 |
| 磁碟 | 5 GB（模型快取） |

### 生產環境（main 分支，Breeze ASR 25，10 人同時使用）

| 項目 | 規格 | 數量 | 用途 |
|------|------|------|------|
| GPU Node | 8 vCPU, 32GB RAM, NVIDIA L4 24GB | 2 台 | API Pod x2（即時轉錄） |
| 磁碟 | NFS 或 local-path | — | model-cache 10Gi |

### 模型 VRAM 需求

| 模型 | VRAM (FP16) | 適合場景 |
|------|-------------|---------|
| large-v2 | 5 GB | 英文技術術語 |
| large-v3 | 5 GB | 多語言通用（OpenAI 最新） |
| Breeze ASR 25 | 5 GB | 台灣華語、中英混用（預設） |

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

## K8s 部署（生產）

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

# 3. Build & Push image
#    方法 A：用 registry（推薦，build 一次所有 Node 都能拉）
REGISTRY=your-registry.com/whisper   # 改成你的 registry
docker build -t $REGISTRY/api:latest -f api/Dockerfile .
docker build -t $REGISTRY/web:latest -f web/Dockerfile web/
docker push $REGISTRY/api:latest
docker push $REGISTRY/web:latest
#    然後修改 k8s/deployment.yaml 和 k8s/web-deployment.yaml 的 image 欄位
#    並將 imagePullPolicy 改為 Always

#    方法 B：無 registry（每台 Node 都要 build）
docker build -t whisper-api:latest -f api/Dockerfile .
docker build -t whisper-web:latest -f web/Dockerfile web/

# 4. 部署
kubectl apply -k k8s/

# 5. 確認
kubectl get pods -n whisper
kubectl port-forward -n whisper svc/web 8080:80
open http://localhost:8080
```

---

## K8s YAML 說明

| 檔案 | 用途 | 維運需修改 |
|------|------|-----------|
| `namespace.yaml` | 建立 `whisper` namespace，隔離資源 | 不需要 |
| `configmap.yaml` | 所有環境變數（模型、VAD 參數等），改這裡不用重建 image | **切換模型、調整參數時改這裡** |
| `pv.yaml` | PersistentVolume，模型快取存放位置 | **生產環境改 NFS Server IP 和路徑** |
| `pvc.yaml` | PersistentVolumeClaim，綁定 PV | 不需要 |
| `deployment.yaml` | API Pod（faster-whisper 轉錄服務） | **改 image 名稱（用 registry 時）、調整 replicas 和資源** |
| `service.yaml` | API Service，帶 sessionAffinity 確保 WebSocket 黏性 | 不需要 |
| `web-deployment.yaml` | 前端 Nginx Pod | **改 image 名稱（用 registry 時）** |
| `web-service.yaml` | 前端 Service | 不需要 |
| `ingress.yaml` | 外部入口，`/api` → API、`/` → 前端 | **改 domain、TLS 設定** |
| `kustomization.yaml` | Kustomize 入口，`kubectl apply -k k8s/` 一次部署全部 | 不需要 |

---

## 常見維運操作

```bash
# 查看 Pod 狀態
kubectl get pods -n whisper

# 查看 API 日誌
kubectl logs -n whisper deployment/api -f

# 查看前端日誌
kubectl logs -n whisper deployment/web -f

# 擴縮容（例如 API 改為 3 個 Pod）
kubectl scale deployment/api -n whisper --replicas=3

# 重啟（不停機，rolling update）
kubectl rollout restart deployment/api -n whisper
kubectl rollout restart deployment/web -n whisper

# 確認 ConfigMap 內容
kubectl get configmap whisper-config -n whisper -o yaml
```

### 切換模型

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

### 故障排除

| 狀況 | 檢查方式 | 可能原因 |
|------|---------|---------|
| Pod `CrashLoopBackOff` | `kubectl logs -n whisper <pod-name>` | 模型下載失敗、記憶體不足（OOM） |
| Pod `Pending` | `kubectl describe pod -n whisper <pod-name>` | PV/PVC 未綁定、Node 資源不足、GPU label 未設定 |
| 前端打不開 | `kubectl get svc,ingress -n whisper` | Ingress 設定錯誤、web Pod 未 Running |
| 轉錄沒反應 | `curl <host>/api/health` | API 回 503 表示模型還在載入，等幾分鐘 |
| WebSocket 斷線 | 檢查 Ingress timeout 設定 | nginx Ingress 預設 60s timeout，需調大 |

### 停止服務

```bash
kubectl delete -k k8s/
```

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

## 本機開發

### Docker Compose

```bash
git clone https://github.com/yanchen184/whisper-service.git
cd whisper-service
git checkout local  # 本機測試用 local 分支

cp .env.example .env
docker compose up -d

open http://localhost:8081
```

### 本機 K8s 測試（Docker Desktop）

> Docker Desktop 內建 K8s，image 與本機 Docker 共用，不需另外匯入

```bash
git checkout local

# 1. 啟用 K8s
#    Docker Desktop → Settings → Kubernetes → Enable Kubernetes → Apply & Restart
#    等待左下角 Kubernetes 圖示變綠色

# 2. 確認 kubectl 指向 Docker Desktop
kubectl config use-context docker-desktop
kubectl get nodes   # 應該看到一個 Ready 的 node

# 3. Build image
docker build -t whisper-api:latest -f api/Dockerfile .
docker build -t whisper-web:latest -f web/Dockerfile web/

# 4. 部署
kubectl apply -k k8s/

# 5. 確認 Pod Running（首次模型下載需等幾分鐘）
kubectl get pods -n whisper -w

# 6. 測試
kubectl port-forward -n whisper svc/web 8080:80
open http://localhost:8080
```

### 本機 K8s 測試（k3d）

> **k3d vs Docker Desktop K8s 差別**：
> - Docker Desktop K8s 共用本機 Docker image，不需匯入；k3d 有獨立 image 空間，需要 `k3d image import`
> - Docker Desktop K8s 只有一個固定叢集；k3d 可以建立多個獨立叢集，互不影響
> - Docker Desktop K8s 跑的是完整 K8s；k3d 跑的是 K3s（輕量版 K8s），資源佔用更少
> - 沒有 Docker Desktop（例如 Linux）或想要獨立叢集時，用 k3d

```bash
git checkout local

# 安裝 k3d
brew install k3d

# 建立叢集
k3d cluster create whisper

# Build image 並匯入 k3d（k3d 有獨立的 image 空間，需要手動匯入）
docker build -t whisper-api:latest -f api/Dockerfile .
docker build -t whisper-web:latest -f web/Dockerfile web/
k3d image import whisper-api:latest whisper-web:latest -c whisper

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

## 分支差異（僅規格不同，程式碼完全一致）

> `main` 為生產配置（Breeze ASR 25 + GPU），`local` 為本機測試配置（base 模型 + CPU）

| 檔案 | 設定 | local | main |
|------|------|-------|------|
| `configmap.yaml` | STREAM_MODEL | `base` | `phate334/Breeze-ASR-25-ct2` |
| | DEVICE | `cpu` | `cuda` |
| | COMPUTE_TYPE | `int8` | `float16` |
| `deployment.yaml` | replicas | 1 | 2 |
| | CPU request / limit | 500m / 2 | 4 / 8 |
| | Memory request / limit | 512Mi / 2Gi | 8Gi / 16Gi |
| | GPU | 無 | `nvidia.com/gpu: 1` |
| | nodeSelector | 無 | `gpu: "true"` |
| `pv.yaml` | 儲存類型 | local-path | NFS |
| `ingress.yaml` | ingressClass | 無（Traefik） | nginx + WebSocket timeout |
| | host | 無 | `whisper.example.com` |
| `docker-compose.yml` | STREAM_MODEL 預設 | `base` | `phate334/Breeze-ASR-25-ct2` |
