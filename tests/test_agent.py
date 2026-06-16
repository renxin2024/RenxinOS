"""agent 模块单元测试（不调用真实 LLM API）。"""

from unittest.mock import MagicMock, patch

import pytest

from src.agent import (
    _build_system_prompt,
    _expand_query_tokens,
    _format_references,
    _tokenize,
    ask_agent,
    ask_agent_with_meta,
    load_chunks,
    retrieve,
)

VALIDATION_QUERY = "GTD 任务 checkbox 只允许写在哪两个地方"


@pytest.mark.skipif(
    not __import__("pathlib").Path(__file__).resolve().parents[1].joinpath("data/chunks.json").is_file(),
    reason="需要先运行 python -m src.ingest 生成 chunks.json",
)
class TestLoadAndRetrieve:
    def test_load_chunks_returns_nonempty_list(self):
        chunks = load_chunks()
        assert isinstance(chunks, list)
        assert len(chunks) >= 90

    def test_load_chunks_uses_cache(self):
        first = load_chunks()
        second = load_chunks()
        assert first is second

    def test_tokenize_mixed_chinese_english(self):
        tokens = _tokenize("GTD 任务 checkbox 全局任务池")
        assert "gtd" in tokens
        assert "checkbox" in tokens
        assert "任务" in tokens

    def test_expand_query_tokens_for_checkbox(self):
        base = _tokenize("checkbox 写在哪")
        expanded = _expand_query_tokens("checkbox 写在哪", base)
        assert "projects" in expanded
        assert "全局任务池" in expanded

    def test_retrieve_validation_query_includes_iron_law_chunk(self):
        hits = retrieve(VALIDATION_QUERY, top_k=8)
        assert hits
        assert any("只改任务池" in hit["content"] for hit in hits)

    def test_retrieve_results_sorted_by_score(self):
        hits = retrieve(VALIDATION_QUERY, top_k=5)
        scores = [hit["score"] for hit in hits]
        assert scores == sorted(scores, reverse=True)


class TestPromptHelpers:
    def test_format_references_empty(self):
        assert "未检索到" in _format_references([])

    def test_format_references_truncates_long_content(self):
        hits = [{"file": "a.md", "heading": "H", "content": "x" * 1000}]
        text = _format_references(hits)
        assert "…" in text

    def test_build_system_prompt_contains_rules(self):
        hits = [{"file": "a.md", "heading": "H", "content": "铁律内容"}]
        prompt = _build_system_prompt(hits)
        assert "参考资料" in prompt
        assert "不要编造" in prompt


class TestAskAgent:
    @patch("src.agent.client.chat.completions.create")
    def test_ask_agent_sends_system_and_user_messages(self, mock_create):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "测试回答"
        mock_create.return_value = mock_response

        answer = ask_agent(VALIDATION_QUERY)

        assert answer == "测试回答"
        mock_create.assert_called_once()
        messages = mock_create.call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert "参考资料" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == VALIDATION_QUERY

    @patch("src.agent.client.chat.completions.create")
    def test_ask_agent_with_meta_includes_stage_timings(self, mock_create):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "测试回答"
        mock_create.return_value = mock_response

        result = ask_agent_with_meta(VALIDATION_QUERY)

        timings = result["timings"]
        assert set(timings) == {"retrieve_ms", "prompt_ms", "llm_ms", "total_ms"}
        for key in timings:
            assert timings[key] >= 0
        assert timings["total_ms"] >= timings["llm_ms"]
