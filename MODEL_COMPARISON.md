# Whisper 語音轉文字 — 方案評估報告

> 測試環境：Apple M2 / 8GB RAM / macOS 13.3 / whisper.cpp 1.8.4 (Metal GPU)
> 測試日期：2026-04-03
> 更新日期：2026-04-07

---

## 一、方案總覽

我們評估了三大類方案，涵蓋開源自建與雲端 API：

| 方案 | 類型 | 適用場景 |
|------|------|---------|
| **A. whisper.cpp（自建）** | 開源，本地 / K8s 部署 | 資料不出站、批次處理、成本控制 |
| **B. faster-whisper（自建）** | 開源，GPU 伺服器 / K8s | 高吞吐量生產環境 |
| **C. OpenAI API（雲端）** | 付費 API | 快速導入、免維運 |

---

## 二、模型家族一覽

### 開源 Whisper 模型

| 模型 | 參數量 | 檔案大小 | 英文 WER | 中文表現 | 速度（相對） |
|------|--------|---------|----------|---------|-------------|
| tiny | 39M | 75 MB | ~15% | 差 | 最快 |
| base | 74M | 142 MB | ~13% | 普通 | 很快 |
| small | 244M | 466 MB | ~10% | 堪用 | 快 |
| **medium** | 769M | 1.5 GB | ~8% | 好 | 中等 |
| large-v2 | 1.55B | 2.9 GB | ~4-5% | 很好 | 慢 |
| large-v3 | 1.55B | 2.9 GB | ~3-4% | 好（但有幻覺風險） | 慢 |
| **large-v3-turbo** | 809M | 1.6 GB | ~4-5% | 很好 | **比 large 快 8 倍** |

> **注意**：OpenAI 已停止開發新 Whisper 模型，large-v3-turbo（2024/10）為最後版本。

### OpenAI 付費 API 模型

| 模型 | WER | 價格 | 特色 |
|------|-----|------|------|
| whisper-1（舊版） | ~7% | $0.006/分鐘 | 支援 SRT/VTT、word-level 時間戳 |
| **gpt-4o-transcribe** | **~2.5%** | $0.006/分鐘 | 最高精度、抗噪能力強 |
| gpt-4o-mini-transcribe | ~3-4% | $0.003/分鐘 | 精度略低、**價格減半** |
| gpt-4o-transcribe-diarize | ~2.5% | $0.006/分鐘 | 含說話者辨識 |

---

## 三、我們的 Demo 實測結果

### 測試內容：K8s 技術教學影片（中英混用）

### 3.1 短音頻測試（9.8 秒）

| 項目 | medium | large-v2 |
|------|--------|----------|
| 轉錄耗時 | **4.2s** | 7.4s |
| 速度比 | 2.3x 即時 | 1.3x 即時 |

### 3.2 長音頻測試（5 分 14 秒）

| 項目 | medium | large-v2 |
|------|--------|----------|
| 轉錄耗時 | **48s** | ~90s |
| 速度比 | **6.5x 即時** | ~3.5x 即時 |

### 3.3 英文技術術語辨識（關鍵差異）

| 原詞 | medium 辨識 | large-v2 辨識 |
|------|------------|--------------|
| Worker | Walker ❌ | **Worker** ✅ |
| Docker | Dock ❌ | **Docker** ✅ |
| kubectl | Cube Control ❌ | **Kubectl** ✅ |
| Minikube | MiniCube ❌ | **Minicube** ✅ |
| Ubuntu | 與幫助 ❌ | **Ubuntu** ✅ |
| Kubelet | Cubelet ❌ | **Kubelet** ✅ |
| Scheduler | Schedule ❌ | **Scheduler** ✅ |
| 映像檔 | 印象檔 ❌ | **映像檔** ✅ |
| 叢集 (cluster) | 重機 ❌ | 重機 ❌ |
| Pod | Part ❌ | Part ❌ |

> **結論**：large-v2 在英文技術術語辨識上**大幅領先** medium，但「叢集」「Pod」等詞兩者皆錯，需後處理修正。

### 3.4 中文語句品質

| 面向 | medium | large-v2 |
|------|--------|----------|
| 語句流暢度 | 好 | 好 |
| 斷句精準度 | 好 | 較好（更自然的斷點） |
| 中英分詞 | 無空格 | 有空格（中英之間） |

---

## 四、方案比較：優勢與劣勢

### 方案 A：whisper.cpp（自建 — CPU 優先）

| | 說明 |
|---|---|
| **優勢** | 資料完全不出站、無 API 費用、支援量化（Q4/Q5/Q8）大幅降低硬體需求、Docker 映像僅 ~500MB、支援 Apple Metal / CUDA |
| **劣勢** | 精度略低於 faster-whisper、不支援 batch 推理、原作者已將重心移至 llama.cpp（正在找新維護者） |
| **最新版本** | v1.8.4（2026-03-19） |
| **適合** | 資安要求高、邊緣部署、CPU-only 環境、Mac 本地開發 |

### 方案 B：faster-whisper（自建 — GPU 優先）

| | 說明 |
|---|---|
| **優勢** | 比原版 Whisper **快 4-8 倍**、VRAM 用量降低 50-70%、內建 Silero VAD（自動過濾靜音）、支援 batch 推理 |
| **劣勢** | 需要 GPU（NVIDIA）、不支援 Apple Metal、Docker 映像 ~4GB |
| **最新版本** | v1.2.1（2025-10-31） |
| **適合** | GPU 伺服器、K8s GPU node pool、高吞吐量生產環境 |

### 方案 C：OpenAI API（雲端）

| | 說明 |
|---|---|
| **優勢** | **精度最高**（WER ~2.5%）、免維運、支援說話者辨識（diarize）、抗噪能力強、快速導入 |
| **劣勢** | 資料需上傳 OpenAI、檔案上限 25MB、gpt-4o-transcribe **不支援 SRT/VTT/word-level 時間戳**（whisper-1 才支援）、持續費用 |
| **適合** | 快速上線、少量音訊、對精度要求極高 |

---

## 五、功能支援矩陣

| 功能 | whisper.cpp | faster-whisper | OpenAI whisper-1 | OpenAI gpt-4o-transcribe |
|------|------------|----------------|------------------|--------------------------|
| 中文支援 | ✅ | ✅ | ✅ | ✅ |
| 英文技術術語 | ✅（large-v2 以上） | ✅（large-v2 以上） | ✅ | ✅（最佳） |
| SRT/VTT 字幕 | ✅ | ✅ | ✅ | ❌ |
| Word-level 時間戳 | ✅ | ✅ | ✅ | ❌ |
| 說話者辨識 | ❌ | ❌（需外掛） | ❌ | ✅（diarize 版） |
| 即時串流 | ✅ | ❌ | ❌ | ✅（Realtime API） |
| 靜音過濾 (VAD) | ❌（需外掛） | ✅（內建） | ✅ | ✅ |
| 資料不出站 | ✅ | ✅ | ❌ | ❌ |
| 自訂術語修正 | ✅（後處理） | ✅（後處理） | ✅（prompt） | ✅（prompt） |

---

## 六、硬體需求

### 各模型最低配置

| 模型 | CPU-only（RAM） | GPU 最低（VRAM） | GPU 建議 |
|------|----------------|-----------------|---------|
| tiny / base | 4 vCPU, 8GB | 不需要 | — |
| small | 8 vCPU, 16GB | 不需要 | — |
| **medium** | 16 vCPU, 32GB | T4 (16GB) | L4 (24GB) |
| **large-v2 / v3** | 不建議（太慢） | L4 (24GB) | A100 (40GB) |
| **large-v3-turbo** | 16 vCPU, 32GB（勉強） | **T4 (16GB) 即可** | L4 (24GB) |

### 速度參考（Real-Time Factor，越小越快）

| 模型 | Mac M2 8GB (CPU) | T4 16GB GPU | A100 40GB GPU |
|------|------------------|-------------|---------------|
| small | 0.5x | 0.05x | 0.02x |
| medium | 1.5x | 0.1x | 0.04x |
| large-v2 | ❌ 記憶體不足 | 0.25x | 0.07x |
| large-v3-turbo | 2.0x（Q4 量化） | 0.08x | 0.03x |

### K8s Worker Node 建議規格

| 方案 | Node 規格 | 每 Node 同時處理量 |
|------|----------|-------------------|
| whisper.cpp + small (CPU) | 8 vCPU, 16GB | 1-2 個同時 |
| faster-whisper + turbo (GPU) | T4, 8 vCPU, 32GB | 1 個同時，排隊 3-5 個 |
| faster-whisper + large-v2 (GPU) | L4, 8 vCPU, 32GB | 1 個同時 |
| faster-whisper + large-v2 (GPU) | A100, 12 vCPU, 64GB | 3-4 個同時 |

---

## 七、成本估算

### 自建方案（K8s，以 GKE 為例）

| GPU 類型 | 月費（On-Demand） | 月費（Spot） | 適用模型 |
|---------|------------------|-------------|---------|
| T4 (16GB) | ~$255/月 | **~$80/月** | medium, large-v3-turbo |
| L4 (24GB) | ~$511/月 | **~$153/月** | large-v2/v3 |
| A100 (40GB) | ~$2,679/月 | **~$803/月** | large-v2 高吞吐 |
| CPU 8 vCPU (e2-standard-8) | ~$197/月 | — | tiny, base, small |

### OpenAI API 方案

| 模型 | 每分鐘 | 每小時 | 100hr/月 | 500hr/月 |
|------|--------|--------|---------|---------|
| gpt-4o-transcribe | $0.006 | $0.36 | **$36** | **$180** |
| gpt-4o-mini-transcribe | $0.003 | $0.18 | **$18** | **$90** |
| whisper-1 | $0.006 | $0.36 | $36 | $180 |

### 損益平衡分析

| 每日音訊量 | 自建（T4 Spot） | OpenAI gpt-4o-transcribe | 哪個划算 |
|-----------|----------------|-------------------------|---------|
| 1 小時/天 | ~$80/月 | ~$11/月 | **OpenAI** |
| 5 小時/天 | ~$80/月 | ~$54/月 | **OpenAI** |
| 8 小時/天 | ~$80/月 | ~$86/月 | **持平** |
| 20 小時/天 | ~$80/月 | ~$216/月 | **自建** |
| 100 小時/天 | ~$120/月 | ~$1,080/月 | **自建（省 9 倍）** |

> **結論**：每天超過 ~8 小時音訊，自建方案開始比 OpenAI API 划算。

---

## 八、推薦方案

### 場景 1：快速驗證 / 少量使用（< 8hr/天）

> **推薦：OpenAI gpt-4o-mini-transcribe API**

- 月費：< $50
- 精度：最高等級
- 導入時間：幾小時
- 限制：資料需上傳 OpenAI、不支援 SRT 格式

### 場景 2：中量生產（8-100hr/天）+ 需要字幕

> **推薦：K8s + faster-whisper + large-v3-turbo + T4 Spot**

- 月費：$80-120
- 精度：接近 large-v2 水準
- 支援：SRT/VTT、word-level 時間戳
- 架構：API → Redis Queue → Worker Pods → 結果存 S3

### 場景 3：資安要求高 / 資料不可出站

> **推薦：K8s + whisper.cpp + large-v2（Q5 量化）+ L4 GPU**

- 月費：$153（Spot）
- 資料：完全不出站
- 支援：所有輸出格式

### 場景 4：邊緣部署 / 低成本

> **推薦：whisper.cpp + small 模型 + CPU Node**

- 月費：$197（CPU node）
- 精度：堪用，技術術語需後處理
- 適合：對精度要求不高的初步轉錄

---

## 九、系統架構設計

### 技術棧

| 元件 | 技術選擇 | 理由 |
|------|---------|------|
| API 層 | **FastAPI** (Python) | async 原生、自動產生 OpenAPI 文件、與轉錄引擎同語言 |
| 任務佇列 | **Redis + arq** | 輕量，Redis 同時兼任 broker 和快取，不需要額外 MQ |
| 資料庫 | **PostgreSQL** | 任務紀錄、使用量統計、持久化（Redis 重啟會丟） |
| 物件儲存 | **MinIO**（自建）/ **S3**（雲端） | 音檔 + 結果存放，S3 相容，未來搬雲端零修改 |
| 轉錄引擎 | **faster-whisper** | GPU 生產首選，速度快 4-8x，內建 VAD |
| 容器化 | **Docker / K8s** | Worker 常駐載入模型，避免重複載入（10-30s） |

### 為什麼需要每個元件

- **API 和 Worker 分離**：轉錄一段 30 分鐘音檔可能跑 5-10 分鐘，不能佔住 API 連線
- **Redis**：API 和 Worker 之間的溝通橋樑 + 即時進度快取
- **PostgreSQL**：持久化任務歷史、計費統計（Redis 不適合當持久儲存）
- **MinIO**：多 Worker 共享檔案的乾淨方案（K8s NFS/PVC ReadWriteMany 問題多）

### 資料流

```
用戶上傳音檔
    │
    ▼
┌──────────┐  儲存音檔   ┌──────────┐
│ FastAPI  │────────────►│  MinIO   │
│ API      │             │  /S3     │
└────┬─────┘             └──────────┘
     │ enqueue
     ▼
┌──────────┐  dequeue    ┌──────────────────┐
│  Redis   │────────────►│ Whisper Worker   │
│  Queue   │◄────────────│ (faster-whisper) │
└──────────┘  更新進度    └───────┬──────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │  MinIO   │ │  Redis   │ │ Postgres │
              │ 存結果   │ │ 狀態快取 │ │ 任務紀錄 │
              └──────────┘ └──────────┘ └──────────┘

用戶查詢 GET /tasks/{id} → Redis（即時）→ 下載結果 → MinIO presigned URL
```

### API 設計

```
POST   /api/v1/transcribe              上傳音檔，回傳 task_id（202 Accepted）
GET    /api/v1/tasks/{task_id}         查詢狀態與進度（0-100%）
GET    /api/v1/tasks/{task_id}/result   下載結果（?format=json|srt|txt）
DELETE /api/v1/tasks/{task_id}         刪除任務與檔案
GET    /api/v1/tasks                   列出所有任務（分頁）
GET    /api/v1/health                  健康檢查
```

### 中英混用特殊處理

```python
# faster-whisper 最佳參數
segments, info = model.transcribe(
    audio_path,
    language=None,                    # 自動偵測，不要鎖定語言
    vad_filter=True,                  # 過濾靜音段
    word_timestamps=True,             # word-level 時間戳
    condition_on_previous_text=True,  # 利用上文改善辨識
    initial_prompt="這是一段關於 Kubernetes、Docker、CI/CD 的技術教學。",
)
```

**術語自動修正（後處理）**：

```python
TERM_CORRECTIONS = {
    "重機": "叢集",
    "Part": "Pod",
    "酷伯内提斯": "Kubernetes",
    "刀可": "Docker",
    # 可由使用者自訂擴充
}
```

### 部署方式

#### 簡單版：Docker Compose（單機 / 小團隊）

```
┌──────────────────────────────────────┐
│         單機 GPU Server              │
│                                      │
│  Nginx (:443)                        │
│    └─► FastAPI (:8000)               │
│           └─► Redis (:6379)          │
│                 └─► Whisper Worker   │
│                      (GPU access)    │
│                                      │
│  PostgreSQL (:5432)  MinIO (:9000)   │
└──────────────────────────────────────┘
```

- 一張 RTX 4090 跑 large-v3，30 分鐘音檔約 2-3 分鐘處理完
- 一天可處理 ~500 個 30 分鐘檔案
- **Phase 1 即可 demo**

#### 生產版：K8s + 自動擴展

```
┌─────────────────────────────────────────────────────┐
│                   K8s Cluster                        │
│                                                     │
│  Ingress (Nginx, TLS, 上傳限制 500MB)               │
│    └─► Deployment: api-server (2-5 replicas, HPA)   │
│                                                     │
│  Deployment: whisper-worker (1-10 replicas, KEDA)   │
│    └─► 每個 Pod 綁 1 張 GPU                         │
│    └─► KEDA 依 Redis 佇列深度自動擴展               │
│                                                     │
│  StatefulSet: redis     (PVC 10Gi)                  │
│  StatefulSet: postgres  (PVC 50Gi)                  │
│  StatefulSet: minio     (PVC 500Gi)                 │
│                                                     │
│  監控: Prometheus + Grafana                          │
└─────────────────────────────────────────────────────┘
```

| K8s 資源 | 用途 |
|---------|------|
| Ingress | TLS 終端、上傳大小限制 |
| HPA | API Server 依 CPU 使用率擴展 |
| KEDA | Worker 依佇列深度擴展（佇列 > 2 就加 Pod） |
| ConfigMap | 模型名稱、語言設定 |
| Secret | DB 密碼、MinIO key、API key |
| PVC | Redis / PostgreSQL / MinIO 持久化 |

### 實作階段

| 階段 | 內容 | 產出 |
|------|------|------|
| **Phase 1** | FastAPI + Worker + Redis + MinIO (Docker Compose) | **可 demo** |
| **Phase 2** | PostgreSQL 整合、API 完善、前端上傳介面 | 完整服務 |
| **Phase 3** | 中英混用後處理、術語修正表 | 提升品質 |
| **Phase 4** | K8s 部署、KEDA 自動擴展 | 生產就緒 |
| **Phase 5** | Prometheus + Grafana 監控 | 可觀測性 |

---

## 十、後續優化方向

1. **自動術語替換表** — 建立中英技術術語對照表（叢集、Pod 等），自動後處理修正
2. **Breeze ASR 25** — 聯發科開源的中文 ASR 模型，若能轉 GGML 格式，中英混用品質預期大幅提升
3. **Hybrid 方案** — 自建 whisper 做初稿 + OpenAI API 做精修，兼顧成本與品質
4. **NVIDIA Canary Qwen 2.5B** — 目前開源 WER 最低（5.63%），但多語言支援待觀察
5. **量化模型** — 使用 whisper-quantize 壓縮模型，進一步降低硬體需求

---

## 十、競爭者觀察（2026 年）

| 模型 | 來源 | WER | 特點 |
|------|------|-----|------|
| NVIDIA Canary Qwen 2.5B | NVIDIA | 5.63% | 開源最強，英文為主 |
| IBM Granite Speech 3.3 8B | IBM | 5.85% | 多語言、Apache 2.0 |
| NVIDIA Parakeet TDT 1.1B | NVIDIA | ~8% | 極快速度，即時串流 |
| Moonshine | Useful Sensors | ≈ large-v3 | 最小 26MB，邊緣裝置 |

> **多語言（中英混用）場景，Whisper 仍是目前最成熟的開源選擇。**
