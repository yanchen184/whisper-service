# 前端對接 API 文件

服務基底 URL：`http://localhost:8000`

---

## 目錄

1. [WebSocket — 即時語音串流](#websocket--即時語音串流)
2. [POST /api/report — AI 評鑑意見產製](#post-apireport--ai-評鑑意見產製)
3. [GET /api/health — 健康檢查](#get-apihealth--健康檢查)
4. [錯誤處理原則](#錯誤處理原則)

---

## WebSocket — 即時語音串流

### 連線

```
ws://localhost:8000/api/stream
```

### 音訊格式要求

前端必須將麥克風音訊重取樣為以下規格後再送出：

| 規格 | 值 |
|------|----|
| 格式 | Raw PCM16 LE（有號 16 位元整數，小端序） |
| 取樣率 | 16,000 Hz |
| 聲道數 | 1（mono） |
| 每包時長 | 30 ms（= 480 samples = 960 bytes） |

每個 WebSocket binary frame 就是一包 PCM16 資料，直接 `ws.send(arrayBuffer)`，不需要任何封裝或 header。

### 前端送出（Binary）

```javascript
// 範例：AudioWorklet 處理後送出
ws.send(pcm16ArrayBuffer);
```

### 後端回傳（JSON）

連線後後端會主動推送 JSON 訊息，前端依 `type` 欄位處理：

| `type` | 時機 | 完整訊息 |
|--------|------|---------|
| `connected` | 連線建立後立即送出 | `{ "type": "connected", "message": "WebSocket 已連接" }` |
| `processing` | 偵測到語音、轉錄進行中 | `{ "type": "processing" }` |
| `transcription` | 轉錄完成 | `{ "type": "transcription", "text": "轉錄結果文字" }` |
| `error` | 發生錯誤 | `{ "type": "error", "message": "錯誤描述" }` |

**注意：**
- `transcription.text` 已去除前後空白
- 轉錄結果為空字串時後端不送出訊息（不需要前端處理空值）
- `processing` 訊息可用來顯示「辨識中...」的 loading 狀態

### 前端監聽範例

```javascript
const ws = new WebSocket('ws://localhost:8000/api/stream');

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  switch (msg.type) {
    case 'connected':
      console.log('已連線');
      break;
    case 'processing':
      showLoadingIndicator();
      break;
    case 'transcription':
      appendText(msg.text);
      hideLoadingIndicator();
      break;
    case 'error':
      showError(msg.message);
      break;
  }
};
```

### VAD 行為說明

後端內建靜音偵測，前端**不需要**自己判斷什麼時候停止送音訊，持續送即可：

- 偵測到有人說話 → 開始緩衝音訊
- 說話停止後靜音超過 1 秒 → 自動觸發轉錄
- 轉錄完成 → 送回 `transcription` 訊息

---

## POST /api/report — AI 評鑑意見產製

委員填完備忘錄與主要意見後，呼叫此端點由 LLM 自動產生條列式評量意見。

### Request

```
POST /api/report
Content-Type: application/json
```

```json
{
  "transcript": "委員備忘錄與主要意見的合併文字",
  "indicator_code": "A1",
  "facility_type": "機構住宿式",
  "facility_subtype": null
}
```

| 欄位 | 型別 | 必填 | 說明 |
|------|------|:----:|------|
| `transcript` | string | ✓ | 委員觀察紀錄，不可為空字串 |
| `indicator_code` | string | ✓ | 評鑑指標代碼，例如 `A1`、`B12`、`C3` |
| `facility_type` | string | | 機構種類，預設 `機構住宿式`；另一個值為 `綜合式` |
| `facility_subtype` | string \| null | | 僅 `facility_type` 為 `綜合式` 時使用，見下表 |

**facility_subtype 可用值（facility_type 為綜合式時）：**

| 值 | 說明 |
|----|------|
| `居家式` | 居家照顧服務 |
| `社區式-日間照顧` | 日間照顧中心 |
| `社區式-小規模多機能` | 小規模多機能服務 |
| `社區式-團體家屋` | 失智症團體家屋 |

> 年份由後端自動取當前民國年（西元年 − 1911），前端**不需要**傳入。

### Response — 成功 `200`

```json
{
  "opinion": "改善事項：\n• 應將性侵害與性騷擾辦法分開訂定。\n• 宜於工作手冊中明列緊急事件聯繫窗口。\n\n建議事項：\n• 宜加強跌倒個案之逐案分析與改善方案。",
  "transcript": "原始委員觀察紀錄文字"
}
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| `opinion` | string | 條列式評量意見。可能僅有改善事項、僅有建議事項、或兩者皆有。**LLM 服務失敗時為空字串**（不會回傳 5xx，前端需自行判斷空值並提示使用者） |
| `transcript` | string | 原樣回傳的輸入 transcript |

**opinion 格式說明：**

```
改善事項：
• 每條以「應」或「宜」開頭
• 每條不超過 60 字

建議事項：
• 每條以「宜加強」或「建議」開頭
• 每條不超過 60 字
```

改善事項與建議事項不一定同時出現，視委員觀察內容而定。

### Response — 錯誤

| 狀態碼 | 情境 | 回傳格式 |
|--------|------|---------|
| `400` | `transcript` 或 `indicator_code` 為空字串 | `{ "error": "transcript 不可為空" }` |
| `502` | LLM 服務無法連線或回傳錯誤 | `{ "error": "LLM 服務錯誤: ..." }` |

### 呼叫範例

```javascript
const response = await fetch('http://localhost:8000/api/report', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    transcript: memoText + '\n' + mainOpinionText,
    indicator_code: 'A1',
    facility_type: '機構住宿式',
  }),
});

const data = await response.json();

if (!response.ok) {
  showError(data.error);
  return;
}

if (!data.opinion) {
  showWarning('AI 產製失敗，請稍後再試或手動填寫');
  return;
}

fillOpinionField(data.opinion);
```

---

## GET /api/health — 健康檢查

確認後端服務與 Whisper 模型是否已就緒，可在連線前先呼叫確認狀態。

### Request

```
GET /api/health
```

### Response — 就緒 `200`

```json
{
  "status": "ok",
  "backend": "faster-whisper",
  "model": "phate334/Breeze-ASR-25-ct2"
}
```

| 欄位 | 說明 |
|------|------|
| `status` | `"ok"` |
| `backend` | `"faster-whisper"` 或 `"whisper.cpp"` |
| `model` | 目前使用的模型名稱 |

### Response — 模型載入中 `503`

```json
{ "status": "loading" }
```

服務剛啟動時模型尚未載入完成會回傳 503，可以 polling 直到回傳 200 再允許使用者連線。

---

## 錯誤處理原則

| 情境 | 後端行為 | 前端建議處理 |
|------|---------|-------------|
| WebSocket 連線失敗 | — | 顯示「無法連線，請確認服務已啟動」 |
| `transcription` 長時間未收到 | 轉錄中正常現象 | `processing` 超過 10 秒可提示使用者 |
| `error` 訊息 | 轉錄失敗 | 顯示錯誤訊息，允許繼續使用 |
| `/api/report` 回傳 `opinion` 為空字串 | LLM 內部失敗，不拋 5xx | 提示使用者手動填寫 |
| `/api/report` 回傳 `502` | LLM 服務未啟動或掛掉 | 顯示「AI 服務暫時無法使用」 |
