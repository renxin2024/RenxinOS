#!/usr/bin/env python3
"""
V3 S4+S5 测试：_real_search_tasks + StateManager/StepRecord/AgentState

不依赖 LLM API，纯逻辑测试。
"""

import json
import tempfile
import os
from pathlib import Path

import pytest

from src.agent_raw.state import AgentState, StepRecord, StateManager
from src.agent_raw.tools import _real_search_tasks, _mock_search_tasks


# =====================================================================
# 辅助函数：构造模拟的任务池 Markdown 内容
# =====================================================================
def _make_task_pool_md(*, with_pending: bool = True) -> str:
    """生成一个结构完整的模拟全局任务池 Markdown 内容。"""
    lines = [
        "## 📍 一眼行动",
        "",
        "| 状态 | 详情 |",
        "|------|------|",
        "| **主块**（13:30–17:30） | V3 S4 tool2 + S5 State dict |",
        "| **副块**（20:00–21:00） | read30《原则》第 5 章 |",
        "| **最急 deadline** | 6/25 儿保复诊 |",
        "",
        "## ☀️ 今日执行",
        "",
        "`2026-06-24`",
        "",
        "**本周**：V3 收尾 + 验收",
        "",
        "### 核心主块",
    ]
    if with_pending:
        lines += [
            "- [ ] S4: 实现 tool 2 — search_tasks 从 mock → 读取真实任务池数据",
            "- [x] S1: ReAct 骨架 ✅",
            "- [ ] S5: State dict + 对话历史管理",
        ]
    else:
        lines += [
            "- [x] S4: 实现 tool 2 ✅",
            "- [x] S1: ReAct 骨架 ✅",
            "- [x] S5: State dict ✅",
        ]

    lines += [
        "",
        "### 习惯打卡",
        "- [ ] 早睡 23:00",
        "- [ ] 喝水 8 杯",
        "",
        "### 备选任务",
        "- [ ] 清理桌面",
    ]

    return "\n".join(lines)


# =====================================================================
# S4: _real_search_tasks 测试
# =====================================================================
class TestRealSearchTasks:
    """测试 _real_search_tasks 从 Markdown 解析任务池数据。"""

    def test_extracts_main_block_and_deadline(self, monkeypatch, tmp_path):
        """验证：能正确提取主块、副块、deadline。"""
        # 构造临时任务池文件
        pool_dir = tmp_path / "tasks"
        pool_dir.mkdir()
        pool_file = pool_dir / "全局任务池.md"
        pool_file.write_text(_make_task_pool_md(), encoding="utf-8")

        # 注入路径：让 _real_search_tasks 读到我们的临时文件
        # monkeypatch Path.exists 不够，需要控制路径解析。
        # 直接 patch 内部逻辑——设置 TODO_DIR 环境变量
        monkeypatch.setenv("TODO_DIR", str(tmp_path))

        result = _real_search_tasks("主块")

        assert "V3 S4 tool2 + S5 State dict" in result
        assert "read30《原则》第 5 章" in result
        assert "6/25 儿保复诊" in result

    def test_extracts_date_and_week_summary(self, monkeypatch, tmp_path):
        """验证：能提取日期和本周摘要。"""
        pool_dir = tmp_path / "tasks"
        pool_dir.mkdir()
        pool_file = pool_dir / "全局任务池.md"
        pool_file.write_text(_make_task_pool_md(), encoding="utf-8")
        monkeypatch.setenv("TODO_DIR", str(tmp_path))

        result = _real_search_tasks("日期")

        assert "2026-06-24" in result
        assert "V3 收尾 + 验收" in result

    def test_extracts_pending_tasks(self, monkeypatch, tmp_path):
        """验证：能提取未完成的待办任务。"""
        pool_dir = tmp_path / "tasks"
        pool_dir.mkdir()
        pool_file = pool_dir / "全局任务池.md"
        pool_file.write_text(_make_task_pool_md(with_pending=True), encoding="utf-8")
        monkeypatch.setenv("TODO_DIR", str(tmp_path))

        result = _real_search_tasks("待办")

        assert "S4: 实现 tool 2" in result
        assert "S5: State dict" in result

    def test_filters_habit_section(self, monkeypatch, tmp_path):
        """验证：习惯打卡区域被正确过滤。"""
        pool_dir = tmp_path / "tasks"
        pool_dir.mkdir()
        pool_file = pool_dir / "全局任务池.md"
        pool_file.write_text(_make_task_pool_md(with_pending=True), encoding="utf-8")
        monkeypatch.setenv("TODO_DIR", str(tmp_path))

        result = _real_search_tasks("待办")

        # 习惯打卡的内容不应出现
        assert "早睡" not in result
        assert "喝水" not in result
        # 备选任务的内容不应出现
        assert "清理桌面" not in result

    def test_no_pending_tasks_shows_none(self, monkeypatch, tmp_path):
        """验证：全部完成时不显示待办列表。"""
        pool_dir = tmp_path / "tasks"
        pool_dir.mkdir()
        pool_file = pool_dir / "全局任务池.md"
        pool_file.write_text(_make_task_pool_md(with_pending=False), encoding="utf-8")
        monkeypatch.setenv("TODO_DIR", str(tmp_path))

        result = _real_search_tasks("待办")

        # 不应该有"待完成任务"标题
        assert "待完成任务" not in result

    def test_file_not_found_returns_error(self, monkeypatch, tmp_path):
        """验证：文件不存在时返回错误信息。"""
        monkeypatch.setenv("TODO_DIR", str(tmp_path))
        # tmp_path 下没有 tasks/全局任务池.md

        result = _real_search_tasks("主块")

        assert "错误" in result
        assert "不存在" in result

    def test_mock_search_tasks_still_works(self):
        """验证：mock 版本作为 fallback 仍然可用。"""
        result = _mock_search_tasks("test")
        assert "模拟任务池结果" in result


# =====================================================================
# S5: StepRecord 测试
# =====================================================================
class TestStepRecord:
    """测试 StepRecord 不可变单步记录。"""

    def test_basic_creation(self):
        record = StepRecord(
            step=1,
            thought="需要查询笔记",
            action="search_notes",
            action_input="GTD checkbox",
            observation="找到了 3 条结果",
        )
        assert record.step == 1
        assert record.thought == "需要查询笔记"
        assert record.action == "search_notes"
        assert record.action_input == "GTD checkbox"
        assert record.observation == "找到了 3 条结果"
        assert record.final_answer is None

    def test_frozen_cannot_modify(self):
        """验证：StepRecord 是不可变的，修改会抛异常。"""
        record = StepRecord(step=1, thought="思考")
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            record.thought = "被修改了"  # type: ignore

    def test_to_scratchpad_line_full(self):
        """验证：完整的 scratchpad 行输出。"""
        record = StepRecord(
            step=1,
            thought="需要搜索",
            action="search_notes",
            action_input="GTD",
            observation="结果：xxx",
        )
        lines = record.to_scratchpad_line()
        assert "Thought: 需要搜索" in lines
        assert "Action: search_notes" in lines
        assert "Action Input: GTD" in lines
        assert "Observation: 结果：xxx" in lines

    def test_to_scratchpad_line_no_action(self):
        """验证：没有 action 时不输出 Action 行。"""
        record = StepRecord(step=1, thought="直接回答", final_answer="答案")
        lines = record.to_scratchpad_line()
        assert "Thought: 直接回答" in lines
        assert "Action:" not in lines

    def test_to_scratchpad_line_no_observation(self):
        """验证：没有 observation 时不输出 Observation 行。"""
        record = StepRecord(step=1, thought="搜索中", action="search_tasks")
        lines = record.to_scratchpad_line()
        assert "Thought: 搜索中" in lines
        assert "Action: search_tasks" in lines
        assert "Observation:" not in lines


# =====================================================================
# S5: AgentState 测试
# =====================================================================
class TestAgentState:
    """测试 AgentState 状态快照。"""

    def test_initial_state(self):
        state = AgentState(question="测试问题")
        assert state.question == "测试问题"
        assert state.current_step == 0
        assert state.is_finished is False
        assert state.last_answer == ""

    def test_add_step_updates_count(self):
        state = AgentState(question="test")
        state.add_step(StepRecord(step=1, thought="第一步"))
        state.add_step(StepRecord(step=2, thought="第二步"))
        assert state.current_step == 2

    def test_is_finished_with_final_answer(self):
        """验证：有 final_answer 时 is_finished 为 True。"""
        state = AgentState(question="test")
        state.add_step(StepRecord(step=1, thought="第一步", final_answer="最终答案"))
        assert state.is_finished is True
        assert state.last_answer == "最终答案"

    def test_is_finished_without_final_answer(self):
        """验证：没有 final_answer 时 is_finished 为 False。"""
        state = AgentState(question="test")
        state.add_step(StepRecord(step=1, thought="第一步", action="search"))
        assert state.is_finished is False

    def test_is_finished_exceeds_max_steps(self):
        """验证：超过最大步数时 is_finished 为 True。"""
        state = AgentState(question="test", max_steps=2)
        state.add_step(StepRecord(step=1, thought="第一步", action="search"))
        state.add_step(StepRecord(step=2, thought="第二步", action="search"))
        assert state.is_finished is True

    def test_last_answer_falls_back_to_thought(self):
        """验证：没有 final_answer 时返回 thought。"""
        state = AgentState(question="test")
        state.add_step(StepRecord(step=1, thought="最后的思考"))
        assert state.last_answer == "最后的思考"

    def test_build_scratchpad_all_steps(self):
        """验证：build_scratchpad 拼接所有步骤。"""
        state = AgentState(question="test")
        state.add_step(StepRecord(step=1, thought="T1", action="A1", action_input="I1", observation="O1"))
        state.add_step(StepRecord(step=2, thought="T2", action="A2", action_input="I2", observation="O2"))

        sp = state.build_scratchpad()
        assert "T1" in sp
        assert "T2" in sp
        assert "A1" in sp
        assert "O2" in sp

    def test_build_scratchpad_keep_recent(self):
        """验证：keep_recent 截断只保留最近 N 步。"""
        state = AgentState(question="test")
        for i in range(1, 6):
            state.add_step(StepRecord(step=i, thought=f"T{i}", action=f"A{i}", observation=f"O{i}"))

        sp = state.build_scratchpad(keep_recent=2)
        # 5 步，保留最近 2 步 → T4、T5 保留，T1~T3 被截断
        assert "T1" not in sp
        assert "T2" not in sp
        assert "T3" not in sp
        assert "T4" in sp
        assert "T5" in sp
        assert "已省略前" in sp  # 截断提示

    def test_to_dict_structure(self):
        """验证：to_dict 输出结构正确。"""
        state = AgentState(question="test", model="deepseek-chat", max_steps=5)
        state.add_step(StepRecord(step=1, thought="T1", action="A1", observation="O1"))
        state.add_step(StepRecord(step=2, thought="T2", final_answer="答案"))

        d = state.to_dict()
        assert d["question"] == "test"
        assert d["model"] == "deepseek-chat"
        assert d["current_step"] == 2
        assert d["is_finished"] is True
        assert len(d["steps"]) == 2
        assert d["steps"][0]["step"] == 1
        assert d["steps"][0]["action"] == "A1"
        assert d["steps"][1]["final_answer"] == "答案"


# =====================================================================
# S5: StateManager 测试
# =====================================================================
class TestStateManager:
    """测试 StateManager 生命周期管理。"""

    def test_start_creates_state(self):
        mgr = StateManager()
        state = mgr.start("测试问题")
        assert state is not None
        assert state.question == "测试问题"
        assert mgr.state is state

    def test_record_adds_step(self):
        mgr = StateManager()
        mgr.start("test")
        mgr.record(StepRecord(step=1, thought="T1", action="A1", observation="O1"))

        assert mgr.state.current_step == 1
        assert mgr.state.steps[0].thought == "T1"

    def test_record_before_start_raises(self):
        """验证：未 start 就 record 会抛异常。"""
        mgr = StateManager()
        with pytest.raises(RuntimeError, match="未初始化"):
            mgr.record(StepRecord(step=1, thought="T1"))

    def test_scratchpad_empty_before_records(self):
        mgr = StateManager()
        mgr.start("test")
        assert mgr.scratchpad() == ""

    def test_scratchpad_after_records(self):
        mgr = StateManager()
        mgr.start("test")
        mgr.record(StepRecord(step=1, thought="需要搜索", action="search", observation="结果"))
        sp = mgr.scratchpad()
        assert "需要搜索" in sp
        assert "search" in sp
        assert "结果" in sp

    def test_is_finished_property(self):
        mgr = StateManager()
        mgr.start("test")
        assert mgr.is_finished is False
        mgr.record(StepRecord(step=1, thought="T1", final_answer="完成"))
        assert mgr.is_finished is True

    def test_answer_property(self):
        mgr = StateManager()
        mgr.start("test")
        assert mgr.answer == ""
        mgr.record(StepRecord(step=1, thought="T1", final_answer="最终答案"))
        assert mgr.answer == "最终答案"

    def test_scratchpad_with_keep_recent(self):
        """验证：StateManager.scratchpad(keep_recent=N) 代理到 AgentState。"""
        mgr = StateManager()
        mgr.start("test")
        for i in range(1, 4):
            mgr.record(StepRecord(step=i, thought=f"T{i}", action=f"A{i}", observation=f"O{i}"))

        sp = mgr.scratchpad(keep_recent=1)
        assert "T1" not in sp
        assert "T3" in sp
        assert "已省略前" in sp
