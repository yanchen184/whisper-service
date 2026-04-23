# 長照機構評鑑 — 即時語音轉錄與 AI 評鑑意見系統

長照評鑑委員操作介面，支援即時語音轉錄，以及根據評鑑指標自動產製條列式評量意見。

- **Repo**：<https://github.com/yanchen184/whisper-service>
- **建置分支**：`main`（`local` 為歷史快照，不要使用）

---

> 📘 **本 README 優先寫給維運團隊**。若你是開發者，請先讀 [開發指南](#開發指南給開發者)。

---

## 系統內的三個 AI 模型（先搞懂再往下看）

系統用到三個獨立模型，**都是 MediaTek Research 出的 Breeze 系列**，但用途完全不同：

| 模型 | 做什麼 | 跑在哪個容器 | 大小 |
|------|--------|-------------|------|
| **Breeze-ASR-25** | 語音 → 文字（語音辨識） | `api` 容器 | ~1.5 GB |
| **paraphrase-multilingual-MiniLM-L12-v2** | 文字 → 向量（RAG 語意搜尋） | `api` 容器 | ~470 MB |
| **Breeze-2-8B** | 文字 → 文字（產評鑑意見） | `llm` 容器 | ~16 GB |

> 📌 **命名說明**：`Breeze-ASR-25` 雖然是基於 OpenAI Whisper 架構微調的模型，本專案跑的**不是**原版 Whisper，是針對台灣口音優化過的 Breeze-ASR-25。下文若出現「faster-whisper」一詞，指的是跑 Breeze-ASR-25 的**推論引擎**（就像 vLLM 是跑 Breeze-2-8B 的推論引擎）。

委員發聲 → Breeze-ASR-25 轉文字 → MiniLM 找相關歷年意見 → Breeze-2-8B 產出條列式評鑑意見。

---

## 一、部署前置資訊

### 三個 image 要 build

| Service | Dockerfile | 大小預估 | 說明 |
|---------|-----------|---------|------|
| `api` | `api/Dockerfile`（context 為 repo root） | ~1.5 GB | FastAPI 後端；**Breeze-ASR-25**（語音辨識）+ **MiniLM**（RAG embedding）兩個模型已預載進 image |
| `llm` | `llm/Dockerfile` | ~20 GB | vLLM 推論引擎 + **Breeze-2-8B** 模型已預載進 image |
| `web` | `web/Dockerfile` | ~30 MB | Nginx 靜態前端 |

### Build 指令

在 repo root 執行：

```bash
docker build -f api/Dockerfile -t <registry>/whisper-api:<tag> .
docker build -f llm/Dockerfile -t <registry>/whisper-llm:<tag> ./llm
docker build -f web/Dockerfile -t <registry>/whisper-web:<tag> ./web
```

> ⚠️ `api` 與 `llm` 在 `docker build` 階段會連 Hugging Face Hub 下載模型，**build 機器需要外網**。Build 完後 image 可離線部署。若公司 registry 在防火牆後，需要設 `HTTPS_PROXY`。

---

## 二、K8s 部署

### K8s 檔案位置

```
k8s/
├── configmap.yaml        # 環境變數（STREAM_MODEL、LLM_MODEL 等）
├── deployment.yaml       # api 服務（2 replicas、8–16 Gi RAM、**CPU only**）
├── llm-deployment.yaml   # LLM 服務（1 replica、1 GPU）
├── service.yaml
├── web-deployment.yaml
├── web-service.yaml
├── ingress.yaml          # nginx ingress + WebSocket timeout
├── namespace.yaml
└── kustomization.yaml
```

### GPU 資源分配（單 GPU 部署）

本專案預設**單 GPU** 配置：

| 服務 | 硬體 | 原因 |
|------|------|------|
| `api`（Breeze-ASR-25 語音辨識 + MiniLM embedding） | **CPU only**（int8 量化） | 模型小（~2 GB），CPU 可用；把 GPU 留給 LLM |
| `llm`（Breeze-2-8B） | **1 顆 GPU**（VRAM ≥ 16 GB） | 8B LLM 非 GPU 不可，CPU 會慢到無法用 |

若未來擴到 2 GPU，可把 `k8s/configmap.yaml` 的 `DEVICE` 改回 `cuda`、`COMPUTE_TYPE` 改回 `float16`，並在 `k8s/deployment.yaml` 的 `resources` 加回 `nvidia.com/gpu: "1"` 與 `nodeSelector / tolerations`。

### 🔴 必須檢查

1. **GPU 節點 label**：`llm-deployment.yaml` 有 `nodeSelector: gpu: "true"`，確認叢集有節點帶這個 label。
2. **GPU device plugin**：`llm` Pod 有 `nvidia.com/gpu` resource request，叢集要裝 `nvidia-device-plugin`。
3. **image registry**：YAML 裡的 `image:` 目前是佔位符 `whisper-api:latest`（`imagePullPolicy: Never`），要改成你們的 registry 路徑。

### 🟡 其他注意事項

- 模型已 bake 進 image，**不需要** PVC 掛 Hugging Face cache。
- `api/data/*.json`（指標索引、few-shot）在 build 時已 COPY 進 image，**不需要**額外 volume。
- `api` 記憶體需求：Breeze-ASR-25 + MiniLM embedding 載入約 8–16 GB，`deployment.yaml` 已設 `limits.memory: 16Gi`。

---

## 三、環境變數

### configmap.yaml 已預設

```yaml
STREAM_MODEL: phate334/Breeze-ASR-25-ct2
LLM_MODEL: MediaTek-Research/Breeze-2-8B-Instruct
DEVICE: cuda
COMPUTE_TYPE: float16
```

完整清單見 [`.env.example`](./.env.example)。

### 🔴 上線前必改

| 項目 | 位置 | 目前值 | 正式上線要改成 |
|------|------|--------|--------|
| `CORS_ORIGINS` | `k8s/configmap.yaml` | **`*`（全開，方便部署測試用）** | 正式網域，例如 `https://whisper.example.com` |
| `host` | `k8s/ingress.yaml` | 佔位符 `whisper.example.com` | 實際網域 |

> ⚠️ **`CORS_ORIGINS` 目前設為 `*` 是為了方便首次部署測通**。正式對外服務前**務必**改為具體網域，否則任何網站都能呼叫本 API（資安風險）。

**正式環境 `CORS_ORIGINS` 範例**：

```yaml
# k8s/configmap.yaml
data:
  CORS_ORIGINS: "https://whisper.example.com,https://admin.example.com"
```

規則：
- 多個網域用**逗號分隔**
- **要帶 protocol**（`https://` / `http://`）
- **不要**加斜線結尾

---

## 四、健康檢查

**端點**：`GET /api/health`

| 回應 | 狀態 |
|------|------|
| `200 {"status":"ok","backend":"faster-whisper","model":"phate334/Breeze-ASR-25-ct2"}` | 正常 |
| `503 {"status":"loading"}` | Breeze-ASR-25 模型還沒載入完（Pod 啟動中） |

> `backend` 欄位的 `faster-whisper` 是**推論引擎名稱**，實際跑的模型看 `model` 欄位。

K8s `readinessProbe` 建議 `initialDelaySeconds: 60–180`（GPU 首次載入模型需要時間，已在 `deployment.yaml` 設為 180）。

---

## 五、⚠️ 已知風險

### 🔴 P0 — 語音辨識端到端未在開發環境驗證過

- 開發機無 GPU，無法跑完整模型，**語音 → 文字** 的完整流程**沒有在開發環境跑通過**。
- 程式碼邏輯已逐行檢查，**第一次真實驗證會發生在 staging**。
- **建議流程**：
  1. 先部 staging，打 `/api/health` 看 200
  2. 用前端說話，確認有字出來
  3. 再切正式環境
- **卡關 log 關鍵字**：`Whisper 模型就緒`（= Breeze-ASR-25 載入完成）、`VectorStore 就緒`（= MiniLM + ChromaDB 就緒）、`Processing audio`、`轉錄失敗`

### 🟡 P1 — 首次 build 需連 Hugging Face Hub

`api/Dockerfile` 與 `llm/Dockerfile` build 時會下載模型（~1.5 GB + ~16 GB）。**build 機器須能連外網**，或設 `HTTPS_PROXY`。

### 🟡 P2 — LLM 吃 VRAM

`llm-deployment.yaml` 的 vLLM 啟動參數：`--dtype half --gpu-memory-utilization 0.4`（佔 40% VRAM）。若 GPU 與其他服務共用，注意記憶體衝突。

---

## 六、回滾

```bash
# 換回前一個 tag
kubectl set image deployment/api api=<registry>/whisper-api:<previous-tag> -n whisper
kubectl rollout status deployment/api -n whisper

# 或一鍵回退到上一個 revision
kubectl rollout undo deployment/api -n whisper
```

### 除錯速查

```bash
# 看 Pod 狀態
kubectl get pods -n whisper

# 看 api log（啟動流程、轉錄錯誤）
kubectl logs -n whisper deployment/api --tail=200 -f

# 看 llm log（vLLM 載入進度）
kubectl logs -n whisper deployment/llm --tail=200 -f

# 進 Pod 看環境變數 / 測健康檢查
kubectl exec -n whisper deployment/api -- env | grep -E "STREAM_MODEL|LLM_|CORS"
kubectl exec -n whisper deployment/api -- curl -s localhost:8000/api/health
```

---

# 開發指南（給開發者）

以下內容寫給要修改程式碼的工程師。

## 架構

```
┌─────────────────────────────────────────────────────┐
│  ltcfeWebDemo/          前端（靜態 HTML）            │
│  ├── index.html         評鑑委員操作主頁面           │
│  └── assets/javascripts/committee-script.js  核心邏輯│
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
    │  + Breeze-ASR-25│  │  + Breeze-ASR-25│
    │  (CPU / CUDA)   │  │  (Vulkan GPU)   │
    └─────────────────┘  └─────────────────┘
                    ┌────────▼────────┐
                    │  LLM (vLLM)     │
                    │  Breeze-2-8B    │
                    │  HTTP :8001     │
                    └─────────────────┘
```

## 技術決策

| 面向 | 選型 | 決策理由 |
|------|------|---------|
| 語音辨識模型 | **Breeze-ASR-25**（MediaTek Research） | 基於 OpenAI Whisper 架構微調，針對台灣口音 / 繁中優化 |
| 語音辨識引擎 | **faster-whisper**（CTranslate2 量化） | 比原版 Whisper 引擎快 2–4 倍、記憶體減半；用它載 Breeze-ASR-25 |
| GPU 彈性 | 雙引擎切換（faster-whisper / whisper.cpp） | NVIDIA 走 CUDA、AMD 走 Vulkan，環境變數切換不改程式碼 |
| 評鑑意見生成 | RAG（ChromaDB + SentenceTransformer + vLLM） | LLM 不知道衛福部最新指標，先查資料再生成 |
| Few-shot 策略 | 語意相似度排序，非隨機抽取 | 用 transcript 對 1578 筆歷年意見做向量搜尋，最相關 3 筆優先 |
| LLM 模型 | Breeze-2-8B（MediaTek Research） | 繁中優化、8B 可在消費級 GPU 執行、地端部署資料不外送 |
| 向量索引管理 | manifest mtime 版本比對 | 來源 JSON 有更動時啟動自動重建 |
| 服務框架 | FastAPI + WebSocket | 非同步處理多連線；WebSocket 做語音串流、HTTP 做單次意見產製 |

## 本機快速啟動（Docker Compose）

```bash
cp .env.example .env
docker compose up -d
```

用瀏覽器開啟 `ltcfeWebDemo/index.html`，頁面頂部輸入 `ws://localhost:8000/api/stream` → 點「連線」。

### 端口

| 服務 | 端口 |
|------|------|
| api | 8000 |
| llm | 8001 |
| web | 8081 |

## 不用 Docker 本地跑

```bash
cd api
pip install -r requirements.txt

# 首次執行：把 Excel/docx 原始資料轉為 JSON 索引
# 需設定環境變數指向原始資料路徑
export INDICATORS_EXCEL=/path/to/indicators.xlsx
export FEWSHOT_DOCX_DIR=/path/to/fewshot_docx_folder
python3 -m app.data_preprocessor

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 測試

單元測試覆蓋 `audio_processor`（VAD 狀態機、WAV 封裝）、`llm_client`（prompt 組裝、錯誤路徑）、`whisper_client`（httpx mock 各錯誤分支）、`config`（CORS validator、extra env 容忍）。

```bash
cd api
pip install -r requirements-dev.txt
pytest            # 全部
pytest -m unit    # 只跑單元測試（預設全是 unit）
pytest -v         # 看每一案例
```

測試不需要 GPU、不連外部服務（LLM / whisper.cpp / Hugging Face 皆 mock）。

## 前端操作流程

1. 連線 WebSocket
2. 展開評鑑題目（如 A1 業務計畫…）
3. 點「備忘錄」麥克風 → 說出現場觀察紀錄
4. 點「主要意見」麥克風 → 補充重點意見
5. 點「AI 產製」→ LLM 整理成條列式填入欄位
6. 視需要手動調整

## 語音辨識引擎切換

兩個引擎都跑同一個模型（Breeze-ASR-25），差別在 GPU 相容性：

- **faster-whisper（預設）**：支援 CPU 與 NVIDIA CUDA，模型在 Docker build 時預載進 image。
- **whisper.cpp（AMD GPU / Vulkan 加速）**：自行啟動 whisper.cpp server → 設定 `WHISPER_CPP_URL=http://<host>:8080/inference`，設定後優先使用。

## 專案結構

```
whisper/
├── api/                              後端
│   ├── app/
│   │   ├── main.py                   FastAPI 入口
│   │   ├── routes.py                 WebSocket /api/stream + POST /api/report
│   │   ├── audio_processor.py        PCM16 幀緩衝 + RMS 能量 VAD
│   │   ├── whisper_client.py         whisper.cpp HTTP client
│   │   ├── llm_client.py             LLM 評鑑意見產製
│   │   ├── data_preprocessor.py      Excel/docx → JSON 索引（離線）
│   │   └── config.py                 pydantic BaseSettings
│   ├── data/
│   │   ├── indicators.json           898 條評鑑指標（112~115 年）
│   │   └── fewshot.json              1578 筆歷年委員意見
│   ├── Dockerfile
│   └── requirements.txt
├── ltcfeWebDemo/                     前端
├── llm/                              vLLM 服務
├── web/                              Nginx 靜態前端 image
├── docs/
│   ├── technical-guide.md            技術選型與概念教學
│   └── frontend-api.md               前端對接 API 文件
├── k8s/                              Kubernetes 部署設定
├── docker-compose.yml
├── .env.example
└── README.md
```

## 相關文件

- [技術選型與概念教學](docs/technical-guide.md)
- [前端對接 API 文件](docs/frontend-api.md)

## 分支差異（僅部署規格不同，程式碼一致）

> **維護策略**：以 `main` 為唯一維護分支；`local` 已凍結為歷史快照，不再更新。本機測試請直接用 `main`，以環境變數覆寫 `STREAM_MODEL` 即可切為輕量 `base` 模型。

| 檔案 | 設定 | local（歷史） | main（生產） |
|------|------|-------|------|
| `configmap.yaml` | STREAM_MODEL | `base` | `phate334/Breeze-ASR-25-ct2` |
| | DEVICE | `cpu` | `cuda` |
| | COMPUTE_TYPE | `int8` | `float16` |
| `deployment.yaml` | replicas | 1 | 2 |
| | CPU request / limit | 500m / 2 | 4 / 8 |
| | Memory request / limit | 512Mi / 2Gi | 8Gi / 16Gi |
| | GPU | 無 | `nvidia.com/gpu: 1` |
| | nodeSelector | 無 | `gpu: "true"` |
| `llm-deployment.yaml` | GPU | 無 | `nvidia.com/gpu: 1` |
| | vLLM args | `--dtype float32` | `--dtype half --gpu-memory-utilization 0.4` |
| `ingress.yaml` | ingressClass | 無（Traefik） | nginx + WebSocket timeout |
| `docker-compose.yml` | STREAM_MODEL 預設 | `base` | `phate334/Breeze-ASR-25-ct2` |
