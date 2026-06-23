#!/usr/bin/env python3
"""
Tests for src.agent_raw.tools — V3 S2 function calling (tool schema + parsing)
"""

import json
import pytest

from src.agent_raw.tools import (
    ToolDef,
    ToolParamDef,
    ToolRegistry,
    ToolCall,
    parse_tool_call,
    format_observation,
    create_default_registry,
)


# =====================================================================
# ToolDef & ToolParamDef
# =====================================================================
class TestToolDef:
    def test_schema_dict_matches_openai_format(self):
        tool = ToolDef(
            name="test_tool",
            description="A test tool",
            parameters=[
                ToolParamDef(name="query", type="string", description="The query", required=True),
                ToolParamDef(name="limit", type="number", description="Max results", required=False),
            ],
            fn=lambda query, limit=5: f"result for {query}",
        )
        schema = tool.schema_dict()
        assert schema["name"] == "test_tool"
        assert schema["description"] == "A test tool"
        assert "query" in schema["parameters"]["properties"]
        assert "limit" in schema["parameters"]["properties"]
        assert schema["parameters"]["required"] == ["query"]

    def test_format_for_prompt(self):
        tool = ToolDef(
            name="search",
            description="Search something",
            parameters=[
                ToolParamDef(name="q", type="string", description="query string"),
            ],
            fn=lambda q: q,
        )
        prompt = tool.format_for_prompt()
        assert "search(" in prompt
        assert "q(string)" in prompt
        assert "[必填]" in prompt


# =====================================================================
# ToolRegistry
# =====================================================================
class TestToolRegistry:
    def _make_registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register(ToolDef(
            name="echo",
            description="Echo back the input",
            parameters=[ToolParamDef(name="text", type="string", description="Text to echo")],
            fn=lambda text: f"Echo: {text}",
        ))
        return reg

    def test_register_and_get(self):
        reg = self._make_registry()
        assert reg.get("echo") is not None
        assert reg.get("nonexistent") is None

    def test_tool_names(self):
        reg = self._make_registry()
        assert reg.tool_names == ["echo"]

    def test_execute_success(self):
        reg = self._make_registry()
        result = reg.execute("echo", text="hello")
        assert result == "Echo: hello"

    def test_execute_unknown_tool(self):
        reg = self._make_registry()
        result = reg.execute("unknown")
        assert "错误" in result
        assert "unknown" in result

    def test_execute_with_exception(self):
        reg = ToolRegistry()
        reg.register(ToolDef(
            name="broken",
            description="Always fails",
            parameters=[ToolParamDef(name="x", type="string")],
            fn=lambda x: 1 / 0,  # ZeroDivisionError
        ))
        result = reg.execute("broken", x="test")
        assert "出错" in result

    def test_format_all_for_prompt(self):
        reg = self._make_registry()
        prompt = reg.format_all_for_prompt()
        assert "echo(" in prompt

    def test_schemas_list(self):
        reg = self._make_registry()
        schemas = reg.schemas_list()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "echo"

    def test_create_default_registry(self):
        reg = create_default_registry()
        assert "search_notes" in reg.tool_names
        assert "search_tasks" in reg.tool_names


# =====================================================================
# parse_tool_call
# =====================================================================
class TestParseToolCall:
    def test_react_text_format(self):
        text = "Thought: I need to search\nAction: search_notes\nAction Input: GTD checkbox"
        result = parse_tool_call(text)
        assert result is not None
        assert result.tool_name == "search_notes"
        assert result.arguments["query"] == "GTD checkbox"

    def test_react_text_format_empty_input(self):
        text = "Thought: let me search\nAction: search_notes\nAction Input:"
        result = parse_tool_call(text)
        assert result is not None
        assert result.tool_name == "search_notes"

    def test_json_tool_call_block(self):
        text = 'Thought: call tool\n```tool_call\n{"name": "search_notes", "arguments": {"query": "GTD"}}\n```'
        result = parse_tool_call(text)
        assert result is not None
        assert result.tool_name == "search_notes"
        assert result.arguments["query"] == "GTD"

    def test_json_code_block(self):
        text = '```json\n{"name": "search_tasks", "arguments": {"query": "deadline"}}\n```'
        result = parse_tool_call(text)
        assert result is not None
        assert result.tool_name == "search_tasks"

    def test_bare_json(self):
        text = '{"name": "search_tasks", "arguments": {"query": "today"}}'
        result = parse_tool_call(text)
        assert result is not None
        assert result.tool_name == "search_tasks"
        assert result.arguments["query"] == "today"

    def test_no_tool_call(self):
        text = "Just some random text without any tool call"
        result = parse_tool_call(text)
        assert result is None

    def test_final_answer_text_not_parsed_as_tool(self):
        text = "Thought: I can answer now\nFinal Answer: The answer is 42"
        # Final Answer text has no Action, so parse_tool_call returns None
        # (This is handled by parse_llm_output, not parse_tool_call)
        result = parse_tool_call(text)
        assert result is None


# =====================================================================
# format_observation
# =====================================================================
class TestFormatObservation:
    def test_with_tool_name(self):
        result = format_observation("found 3 results", "search_notes")
        assert "[search_notes]" in result
        assert "found 3 results" in result

    def test_without_tool_name(self):
        result = format_observation("some result")
        assert "[工具结果]" in result

    def test_truncation(self):
        long_text = "x" * 2000
        result = format_observation(long_text)
        assert len(result) < 2000
        assert "已截断" in result
