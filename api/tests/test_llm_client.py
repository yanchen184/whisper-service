"""llm_client 單元測試：工具函式 + generate_report（httpx mock）。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app import llm_client
from app.llm_client import (
    _build_fewshot_block,
    _build_user_message,
    _current_roc_year,
    _truncate_spec,
    generate_report,
)


@pytest.mark.unit
class TestRocYear:
    def test_roc_year_is_gregorian_minus_1911(self) -> None:
        assert _current_roc_year() == datetime.now().year - 1911


@pytest.mark.unit
class TestTruncateSpec:
    def test_short_spec_is_unchanged(self) -> None:
        spec = "簡短基準說明"
        assert _truncate_spec(spec) == spec

    def test_long_spec_is_truncated_with_marker(self) -> None:
        from app.config import LLM_SPEC_MAX_CHARS

        spec = "甲" * (LLM_SPEC_MAX_CHARS + 100)
        result = _truncate_spec(spec)
        assert len(result) == LLM_SPEC_MAX_CHARS + len("…（略）")
        assert result.endswith("…（略）")

    def test_spec_exactly_at_limit_is_unchanged(self) -> None:
        from app.config import LLM_SPEC_MAX_CHARS

        spec = "乙" * LLM_SPEC_MAX_CHARS
        assert _truncate_spec(spec) == spec


@pytest.mark.unit
class TestFewshotBlock:
    def test_empty_examples_returns_placeholder(self) -> None:
        assert _build_fewshot_block([]) == "（無歷年範例）"

    def test_examples_formatted_with_type_and_year(self) -> None:
        examples = [
            {"類型": "改善", "年度": 113, "意見": "應訂定相關辦法。"},
            {"類型": "建議", "年度": 112, "意見": "宜加強訓練紀錄。"},
        ]
        block = _build_fewshot_block(examples)
        assert "【改善事項 · 113年】" in block
        assert "應訂定相關辦法。" in block
        assert "【建議事項 · 112年】" in block
        assert "宜加強訓練紀錄。" in block


@pytest.mark.unit
class TestBuildUserMessage:
    def test_all_sections_present(self) -> None:
        transcript = "今天巡視發現門禁未鎖。"
        indicator = {"指標內容": "A1 業務計畫", "基準說明": "應訂定年度計畫"}
        examples = [{"類型": "改善", "年度": 113, "意見": "應訂定計畫。"}]

        msg = _build_user_message(transcript, indicator, examples)
        assert "A1 業務計畫" in msg
        assert "應訂定年度計畫" in msg
        assert "【改善事項 · 113年】" in msg
        assert transcript in msg

    def test_missing_indicator_fields_fallback_to_empty(self) -> None:
        msg = _build_user_message("t", {}, [])
        assert "（無歷年範例）" in msg
        assert "t" in msg


# ──────────────────────────────────────────────
# generate_report 行為測試（mock httpx + VectorStore）
# ──────────────────────────────────────────────

_FAKE_INDICATOR = {
    "指標內容": "A1 業務計畫之訂定",
    "基準說明": "應訂定年度業務計畫並落實執行。",
}
_FAKE_FEWSHOT = [{"類型": "改善", "年度": 113, "意見": "應訂定年度計畫。"}]


class _FakeVectorStore:
    def __init__(self, indicator: dict | None = _FAKE_INDICATOR):
        self._indicator = indicator

    def get_indicator(self, year: int, type_key: str, code: str) -> dict | None:
        return self._indicator

    def get_fewshot(self, code: str, query: str, n: int) -> list[dict]:
        return _FAKE_FEWSHOT


def _mock_llm_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
    )


@pytest.mark.unit
class TestGenerateReport:
    async def test_returns_llm_content_on_success(self) -> None:
        with patch.object(llm_client, "get_vector_store", return_value=_FakeVectorStore()):
            with patch.object(
                llm_client,
                "_call_llm",
                new=AsyncMock(return_value="改善事項：\n• 應訂定計畫。"),
            ):
                result = await generate_report("今天觀察到...", indicator_code="A1")

        assert result["transcript"] == "今天觀察到..."
        assert "改善事項" in result["opinion"]

    async def test_returns_empty_opinion_when_indicator_not_found(self) -> None:
        with patch.object(
            llm_client, "get_vector_store", return_value=_FakeVectorStore(indicator=None)
        ):
            result = await generate_report("任意觀察", indicator_code="ZZ9")

        assert result == {"opinion": "", "transcript": "任意觀察"}

    async def test_http_error_returns_empty_opinion(self) -> None:
        err = httpx.HTTPStatusError(
            "boom",
            request=httpx.Request("POST", "http://llm/v1/chat/completions"),
            response=httpx.Response(500),
        )
        with patch.object(llm_client, "get_vector_store", return_value=_FakeVectorStore()):
            with patch.object(llm_client, "_call_llm", new=AsyncMock(side_effect=err)):
                result = await generate_report("觀察內容", indicator_code="A1")
        assert result == {"opinion": "", "transcript": "觀察內容"}

    async def test_timeout_returns_empty_opinion(self) -> None:
        with patch.object(llm_client, "get_vector_store", return_value=_FakeVectorStore()):
            with patch.object(
                llm_client, "_call_llm", new=AsyncMock(side_effect=httpx.TimeoutException("slow"))
            ):
                result = await generate_report("觀察內容", indicator_code="A1")
        assert result == {"opinion": "", "transcript": "觀察內容"}

    async def test_generic_http_error_returns_empty_opinion(self) -> None:
        with patch.object(llm_client, "get_vector_store", return_value=_FakeVectorStore()):
            with patch.object(
                llm_client,
                "_call_llm",
                new=AsyncMock(side_effect=httpx.ConnectError("unreachable")),
            ):
                result = await generate_report("觀察內容", indicator_code="A1")
        assert result == {"opinion": "", "transcript": "觀察內容"}

    async def test_opinion_text_is_stripped(self) -> None:
        with patch.object(llm_client, "get_vector_store", return_value=_FakeVectorStore()):
            with patch.object(
                llm_client, "_call_llm", new=AsyncMock(return_value="\n\n意見內容\n\n")
            ):
                result = await generate_report("觀察", indicator_code="A1")
        assert result["opinion"] == "意見內容"
