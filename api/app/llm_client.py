"""LLM 評鑑意見產製模組。

流程（逐題觸發，前端明確傳入指標代碼）：
  1. 從 VectorStore 精確查出指標的基準說明與評分標準
  2. 從 VectorStore 以語意相似度取出最相關的 n 筆歷年意見（few-shot）
  3. 組裝 prompt，呼叫 LLM 產生條列式評量意見
  4. 回傳 {"opinion": str, "transcript": str}

設計原則：
- 無模組層級可變狀態，所有狀態由 VectorStore 單例管理
- Prompt 長度保護：基準說明截至 LLM_SPEC_MAX_CHARS 字元
- few-shot 語意排序：與 transcript 最相似的意見優先，而非隨機抽取
- LLM 呼叫錯誤不向上拋，回傳空 opinion 並記錄 error log
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from app.config import (
    LLM_BASE_URL,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_SPEC_MAX_CHARS,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
)
from app.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# ── Prompt 模板 ───────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
你是長照機構評鑑委員的撰寫助手，使用繁體中文。

根據委員的觀察紀錄，產生符合評鑑格式的條列式評量意見。

【輸出規則】
- 視內容決定是否需要改善事項或建議事項，不強制兩者都要
- 改善事項：必須立即改善的缺失，每條以「應」或「宜」開頭
- 建議事項：建議加強的項目，每條以「宜加強」或「建議」開頭
- 每條不超過 60 字，語氣專業客觀
- 嚴格依據委員說的內容，不自行補充未提及的問題

【個資去識別化規則】
- 輸出中不得出現任何真實人名、機構名稱
- 人名依出現順序以代碼取代：第一位→「人員甲」、第二位→「人員乙」、第三位→「人員丙」，以此類推
- 機構名稱以「該機構」取代
- 同一人在整份輸出中必須使用同一代碼

【輸出格式範例】
改善事項：
• 應將性侵害與性騷擾辦法分開訂定。
• 宜於工作手冊中明列緊急事件聯繫窗口。

建議事項：
• 宜加強跌倒個案之逐案分析與改善方案。
"""

_USER_TEMPLATE = """\
## 評鑑指標
{指標內容}

## 基準說明
{基準說明}

## 歷年委員意見範例（供參考語氣與格式，請勿直接複製）
{範例區塊}

## 委員觀察紀錄
{transcript}

請根據委員觀察紀錄，產生本指標的評量意見：\
"""

# ── 工具函式 ──────────────────────────────────────────────────────────────────

def _current_roc_year() -> int:
    """回傳當前民國年（西元年 − 1911）。"""
    return datetime.now().year - 1911


def _truncate_spec(spec: str) -> str:
    """將基準說明截至 LLM_SPEC_MAX_CHARS 字元，保護 prompt token 預算。"""
    if len(spec) <= LLM_SPEC_MAX_CHARS:
        return spec
    return spec[:LLM_SPEC_MAX_CHARS] + "…（略）"


def _build_fewshot_block(examples: list[dict]) -> str:
    """將 few-shot 範例組成 prompt 區塊文字。"""
    if not examples:
        return "（無歷年範例）"
    blocks = [
        f"【{ex['類型']}事項 · {ex['年度']}年】\n{ex['意見']}"
        for ex in examples
    ]
    return "\n\n".join(blocks)


def _build_user_message(transcript: str, indicator: dict, examples: list[dict]) -> str:
    """組裝最終 user message。"""
    return _USER_TEMPLATE.format(
        指標內容=indicator.get("指標內容", ""),
        基準說明=_truncate_spec(indicator.get("基準說明", "")),
        範例區塊=_build_fewshot_block(examples),
        transcript=transcript,
    )


# ── LLM 呼叫 ─────────────────────────────────────────────────────────────────

async def _call_llm(system: str, user: str) -> str:
    """呼叫 LLM OpenAI-compatible API，回傳原始字串。

    Raises:
        httpx.HTTPStatusError: 後端回應非 2xx。
        httpx.TimeoutException: 請求逾時。
    """
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": LLM_MAX_TOKENS,
                "temperature": LLM_TEMPERATURE,
            },
        )
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ── 公開介面 ──────────────────────────────────────────────────────────────────

async def generate_report(
    transcript: str,
    indicator_code: str,
    facility_type: str = "機構住宿式",
    facility_subtype: str | None = None,
) -> dict[str, Any]:
    """針對單一指標，根據委員觀察紀錄產生條列式評量意見。

    Args:
        transcript: 委員備忘錄與主要意見的合併文字。
        indicator_code: 評鑑指標代碼，例如 A1、B12、C3。
        facility_type: 機構種類，「機構住宿式」或「綜合式」。
        facility_subtype: 綜合式子類別，例如「居家式」、「社區式-日間照顧」。

    Returns:
        {
            "opinion": "改善事項：\n• ...\n建議事項：\n• ...",
            "transcript": "原始委員觀察紀錄"
        }
        LLM 呼叫失敗時 opinion 為空字串，不向上拋例外。
    """
    year = _current_roc_year()

    # 組合機構種類 key
    type_key = (
        f"綜合式_{facility_subtype}"
        if facility_type == "綜合式" and facility_subtype
        else facility_type
    )

    vs = get_vector_store()

    # 1. 精確查指標（含 fallback）
    indicator = vs.get_indicator(year, type_key, indicator_code)
    if not indicator:
        return {"opinion": "", "transcript": transcript}

    # 2. 語意搜尋最相關的歷年意見
    fewshot_examples = vs.get_fewshot(indicator_code, query=transcript, n=3)

    # 3. 組裝 prompt 並呼叫 LLM
    user_msg = _build_user_message(transcript, indicator, fewshot_examples)
    try:
        opinion_text = await _call_llm(_SYSTEM_PROMPT, user_msg)
        return {"opinion": opinion_text.strip(), "transcript": transcript}
    except httpx.HTTPStatusError as e:
        logger.error("LLM HTTP 錯誤 [%s %s]: %s", indicator_code, e.response.status_code, e)
    except httpx.TimeoutException:
        logger.error("LLM 請求逾時 [%s]", indicator_code)
    except httpx.HTTPError as e:
        logger.error("LLM 連線錯誤 [%s]: %s", indicator_code, e)

    return {"opinion": "", "transcript": transcript}
