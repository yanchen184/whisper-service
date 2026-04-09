import logging

import httpx

from app.config import LLM_BASE_URL, LLM_MAX_TOKENS, LLM_MODEL, LLM_TEMPERATURE, LLM_TIMEOUT

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是繁體中文文書助理。根據使用者提供的語音轉錄文字，完成以下三個任務：

1. **潤飾**：修正錯字、補標點符號、整理語句使其通順自然
2. **Tag 分類**：判斷內容屬於哪種類型，從以下選擇一個：meeting（會議記錄）、medical（醫療紀錄）、interview（訪談紀錄）、memo（備忘錄）、other（其他）
3. **套模板**：根據分類，將內容整理成對應的結構化格式

請回傳 JSON 格式（不要加 markdown code block）：

若 tag 為 meeting：
{"tag":"meeting","polished":"潤飾後完整文字","structured":{"title":"會議主題","date":"日期（如有提及）","participants":["與會人員"],"summary":"會議摘要","action_items":["待辦事項"],"decisions":["決議事項"]}}

若 tag 為 medical：
{"tag":"medical","polished":"潤飾後完整文字","structured":{"patient":"患者資訊","chief_complaint":"主訴","history":"病史","assessment":"評估","plan":"處置計畫"}}

若 tag 為 interview：
{"tag":"interview","polished":"潤飾後完整文字","structured":{"interviewee":"受訪者","topic":"主題","key_points":["重點摘錄"],"quotes":["重要引述"]}}

若 tag 為 memo：
{"tag":"memo","polished":"潤飾後完整文字","structured":{"subject":"主旨","body":"內容","action_required":["需要處理的事項"]}}

若 tag 為 other：
{"tag":"other","polished":"潤飾後完整文字","structured":{"title":"標題","content":"整理後內容"}}

欄位如果沒有相關資訊，填入 null 或空陣列。"""


async def generate_report(transcript: str) -> dict:
    """呼叫 vLLM 產生結構化報告"""
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"請處理以下語音轉錄文字：\n---\n{transcript}\n---"},
                ],
                "max_tokens": LLM_MAX_TOKENS,
                "temperature": LLM_TEMPERATURE,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]

    import json
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM 回傳非 JSON，原始內容: %s", content[:200])
        return {"tag": "other", "polished": content, "structured": {"title": "LLM 輸出", "content": content}}
