# 技術選型與概念教學

這份文件解釋本專案用到的每個技術是什麼、為什麼選它，適合剛接觸語音 AI 或 RAG 的開發者閱讀。

---

## 目錄

1. [整體架構概念](#整體架構概念)
2. [語音轉錄：Whisper 是什麼](#語音轉錄whisper-是什麼)
3. [為什麼用 faster-whisper，不用原版 Whisper](#為什麼用-faster-whisper不用原版-whisper)
4. [whisper.cpp 是另一個選項](#whispercpp-是另一個選項)
5. [VAD：怎麼知道什麼時候該轉錄](#vad怎麼知道什麼時候該轉錄)
6. [RAG：為什麼不直接問 LLM](#rag為什麼不直接問-llm)
7. [向量資料庫：ChromaDB + SentenceTransformer](#向量資料庫chromadb--sentencetransformer)
8. [Few-shot：給 LLM 看範例](#few-shot給-llm-看範例)
9. [LLM 推論：vLLM + Breeze-2](#llm-推論vllm--breeze-2)
10. [FastAPI + WebSocket](#fastapi--websocket)
11. [為什麼用 Docker](#為什麼用-docker)

---

## 整體架構概念

這個系統做兩件事：

**1. 即時語音轉文字**
委員對著麥克風說話 → 瀏覽器把聲音切成小段送給後端 → 後端用 Whisper 模型轉成文字 → 文字回傳顯示在畫面上。

**2. AI 幫忙寫評鑑意見**
委員輸入觀察紀錄 → 後端查出這題的指標要求 + 找出歷年委員怎麼寫這題 → 把這些資料餵給 LLM → LLM 生成格式化的評量意見。

兩件事都在同一個 FastAPI 後端處理，分別走 WebSocket（長連線串流）和 HTTP（一次性請求）。

---

## 語音轉錄：Whisper 是什麼

Whisper 是 OpenAI 在 2022 年開源的語音辨識模型，支援 99 種語言，中文辨識品質在開源模型裡屬於前段。

模型有不同大小：

| 模型 | 參數量 | 速度 | 準確度 |
|------|--------|------|--------|
| tiny | 39M | 最快 | 最低 |
| base | 74M | 快 | 普通 |
| small | 244M | 中 | 不錯 |
| medium | 769M | 慢 | 好 |
| large | 1.5B | 最慢 | 最好 |

本專案預設用 `phate334/Breeze-ASR-25-ct2`，這是針對繁體中文微調過的版本，在台灣口音的辨識率比原版 Whisper 好很多。

---

## 為什麼用 faster-whisper，不用原版 Whisper

原版 Whisper 用 PyTorch 跑，記憶體佔用大、速度偏慢。

`faster-whisper` 用 CTranslate2 重新實作，把模型量化成 int8：
- **速度**：比原版快 2–4 倍
- **記憶體**：少 50% 以上
- **相容性**：支援 CPU、CUDA，不需要 GPU 也能跑

量化的概念：原本模型的數值是 float32（32 位元），量化成 int8（8 位元）後精度略降但幾乎感覺不出來，換來大幅的速度與記憶體優勢。

---

## whisper.cpp 是另一個選項

`whisper.cpp` 是用純 C++ 重寫的 Whisper，支援 Vulkan GPU（AMD 顯卡也能跑）。

本專案支援兩種後端切換：

```
WHISPER_CPP_URL 為空  →  使用 faster-whisper（Python，內建）
WHISPER_CPP_URL 有設定  →  透過 HTTP 呼叫外部 whisper.cpp server
```

這樣設計的好處：有 NVIDIA GPU 的機器用 faster-whisper + CUDA，有 AMD GPU 的機器用 whisper.cpp + Vulkan，同一份程式碼適應不同硬體。

---

## VAD：怎麼知道什麼時候該轉錄

VAD（Voice Activity Detection，語音活動偵測）解決一個問題：**麥克風一直開著，但不能每 30ms 就送一次轉錄請求**，這樣太浪費資源，而且 Whisper 對太短的音訊效果不好。

本專案的 VAD 邏輯（`audio_processor.py`）：

```
每收到一個 PCM 音訊幀
  ↓
計算 RMS 能量（一種衡量音量的方式）
  ↓
RMS > 300  →  有人在說話，開始收集音訊
RMS ≤ 300 且已有語音  →  開始計靜音時間
靜音超過 1 秒  →  觸發轉錄，清空緩衝區
```

RMS（Root Mean Square）就是把每個取樣值平方、取平均、再開根號，數值越大代表聲音越大。靜音的 RMS 接近 0，說話時通常超過幾百。

除了自己的 VAD，faster-whisper 本身也內建 Silero VAD，兩層過濾讓靜音段不進模型，減少幻覺（Whisper 有時會對靜音輸出莫名其妙的文字）。

---

## RAG：為什麼不直接問 LLM

直接問 LLM「幫我寫 A1 指標的評鑑意見」有幾個問題：

1. LLM 不知道衛福部 114 年的評鑑指標內容
2. LLM 不知道這間機構的評鑑標準
3. LLM 生成的意見風格可能和實際評鑑格式不符

RAG（Retrieval-Augmented Generation）的做法：**先查資料，再生成**。

```
查詢：A1 指標 + 委員觀察紀錄
  ↓
從資料庫撈出：A1 的指標內容、基準說明
  ↓
從歷年資料找出：3 筆委員寫 A1 的真實意見範例
  ↓
把這些塞進 prompt 送給 LLM
  ↓
LLM 根據真實資料生成，不是憑空想像
```

這樣生成的意見準確度高、格式一致，也符合當年度的評鑑標準。

---

## 向量資料庫：ChromaDB + SentenceTransformer

### 為什麼需要向量資料庫

找「最相關的歷年意見」不能用關鍵字搜尋。例如委員說「護理紀錄缺乏連貫性」，歷年資料裡可能寫的是「個案紀錄未定期更新」，關鍵字不同但意思相近。

向量資料庫把文字轉成數字陣列（向量），語意相近的文字向量距離也近，所以可以做「語意搜尋」。

### SentenceTransformer

用來把文字轉成向量的模型。本專案用 `paraphrase-multilingual-MiniLM-L12-v2`，這個模型：
- 支援多語言（含繁中）
- 模型小（約 120MB），CPU 就能跑
- 語意表達品質在小型模型裡算不錯

### ChromaDB

本地向量資料庫，不需要架設外部服務，資料存在本機資料夾。特色：
- 支援 metadata 過濾（先篩 code == "A1"，再做向量搜尋）
- 持久化儲存，重啟後資料還在
- Python 原生，不需要額外依賴

### 版本管理機制

資料更新時要重建向量索引（因為文字變了，向量也要重新計算）。本專案用 `manifest.json` 記錄來源 JSON 的最後修改時間，服務啟動時自動比對，有差異就重建，不用手動觸發。

---

## Few-shot：給 LLM 看範例

Few-shot 是讓 LLM 輸出更穩定的技巧：在 prompt 裡附上幾個「輸入 → 輸出」的真實範例，LLM 會學著按照同樣的格式和語氣生成。

本專案的 few-shot 來源是 112~114 年的真實委員評鑑意見（1578 筆），按指標代碼分類。

關鍵設計：**不是隨機抽 3 筆，而是找最相關的 3 筆**。用委員的觀察紀錄（transcript）對歷年意見做向量相似度排序，語意最接近的排前面，這樣範例對 LLM 的參考價值更高。

---

## LLM 推論：vLLM + Breeze-2

### vLLM

vLLM 是專為大型語言模型設計的推論框架，提供 OpenAI-compatible API（和 OpenAI 的 API 格式一樣），所以後端的 LLM 呼叫代碼可以不用改，只要換 `base_url` 就能切換模型。

主要優點是 PagedAttention 機制，讓 GPU 記憶體使用更有效率，適合需要跑推論服務的場景。

### Breeze-2-8B

MediaTek Research 基於 Llama-3 微調的繁體中文模型，8B 參數（80億），在繁中理解和生成上比 Llama 原版明顯好。選這個模型的原因：
- 繁體中文優化（評鑑意見是繁中專業用語）
- 8B 在消費級 GPU（如 RTX 3090）可跑
- 開源免費，可以地端部署，資料不出去

---

## FastAPI + WebSocket

### 為什麼用 FastAPI

FastAPI 是 Python 的非同步 Web 框架，適合這個專案的原因：
- 原生支援 WebSocket（語音串流需要長連線）
- async/await 非同步，多個委員同時連線不會互相阻塞
- pydantic 型別驗證，API 參數錯誤會自動回報清楚的錯誤訊息

### WebSocket vs HTTP

| | HTTP | WebSocket |
|--|------|-----------|
| 連線 | 每次請求建立、結束 | 一次建立，保持連線 |
| 方向 | 單向（client 問，server 答） | 雙向（任一方都可主動送） |
| 適合 | 查詢、表單送出 | 即時串流、聊天 |

語音轉錄用 WebSocket：前端持續送音訊，後端隨時把轉錄結果推回去，不需要前端一直輪詢。

AI 產製意見用 HTTP POST：一次性請求，等 LLM 回答，HTTP 就夠用。

---

## 為什麼用 Docker

三個服務（api、llm、web）各自有不同的依賴和環境需求：

- `api`：Python 3.11 + faster-whisper + chromadb
- `llm`：vLLM + CUDA（GPU 推論）
- `web`：Nginx 靜態伺服器

用 Docker 的好處：
- 每個服務在自己的 container，依賴不衝突
- `docker compose up` 一個指令全部啟動
- 模型在 build time 預載進 image，部署時不需要網路
- GPU 支援透過 docker compose 的 `deploy.resources` 設定，不需要修改程式碼
