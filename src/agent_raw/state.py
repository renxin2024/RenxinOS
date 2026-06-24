#!/usr/bin/env python3
"""
Renxin OS — V3 S5 State dict + 对话历史管理

核心概念：
- AgentState：一次 ReAct 循环的完整状态快照
  类比 Java：类似一个 RequestContext POJO，持有当前请求的所有上下文数据
- StepRecord：单步操作的不可变记录
  类比 Java：类似 log4j 的 LogEvent，每步一条不可变记录
- StateManager：状态管理器，负责状态更新和历史裁剪
  类比 Java：类似 Spring 的 SessionManager，管理对话生命周期

V3 设计决策：
1. 不用 LangGraph StateGraph（那是 V4 框架做的事）
2. 用 Python dataclass + dict 手写，理解「状态是什么」
3. 支持消息列表存储（结构化）而非纯字符串拼接
4. 支持历史截断（保留最近 N 轮），为长对话做铺垫

V3→V4 对比：
- V3（本文件）：AgentState dataclass → dict → 手动管理
- V4：LangGraph StateGraph → TypedDict → 框架自动管理
- 面试亮点：能对比手写 State dict vs 框架 StateGraph 的抽象层次差异
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# =====================================================================
# 1. StepRecord — 单步操作的不可变记录
# =====================================================================
@dataclass(frozen=True)
class StepRecord:
    """
    一次 ReAct 步骤的完整记录。

    设计为 frozen=True（不可变），原因：
    - 每一步一旦执行完，就不应被修改（类似日志的不可变性）
    - 方便 trace/debug：不会出现「某步记录后来被改了」的诡异 bug
    - 类比 Java：类似 ImmutableList 或 record 类型

    字段：
        step: 步序号（从 1 开始）
        thought: 模型的思考内容
        action: 调用的工具名（None 表示未调用工具，直接给出答案）
        action_input: 传给工具的输入
        observation: 工具返回的结果（None 表示尚未执行）
        final_answer: 最终答案（None 表示循环未终止）
        raw_output: LLM 原始输出（用于 debug）
    """
    step: int
    thought: str = ""
    action: str | None = None
    action_input: str = ""
    observation: str | None = None
    final_answer: str | None = None
    raw_output: str = ""

    def to_scratchpad_line(self) -> str:
        """
        将本步转换为 ReAct scratchpad 格式的文本行。

        用于拼接历史上下文，喂给下一轮 LLM。
        类比 Java：类似 toString() 用于日志输出
        """
        lines = [f"Thought: {self.thought}"]
        if self.action:
            lines.append(f"Action: {self.action}")
            lines.append(f"Action Input: {self.action_input or ''}")
        if self.observation:
            lines.append(f"Observation: {self.observation}")
        return "\n".join(lines) + "\n"


# =====================================================================
# 2. AgentState — 一次 ReAct 循环的完整状态
# =====================================================================
@dataclass
class AgentState:
    """
    Agent 的完整运行时状态。

    类比 Java：类似一个 Session 或 RequestContext 对象，包含：
    - 用户问题（question）
    - 已执行的步骤列表（steps）
    - 元数据（模型、最大步数、当前步序号）

    为什么不用简单的 dict：
    - dataclass 有类型提示，IDE 能自动补全
    - 不可变字段（如 question、model）用 frozen 保护
    - 可变字段（如 steps）用 list 操作，清晰可控
    """
    question: str
    model: str = "deepseek-chat"
    max_steps: int = 5
    steps: list[StepRecord] = field(default_factory=list)

    @property
    def current_step(self) -> int:
        """当前已执行的步数（从 1 开始）。"""
        return len(self.steps)

    @property
    def is_finished(self) -> bool:
        """循环是否已终止（有 final_answer 或超步数）。"""
        if not self.steps:
            return False
        last = self.steps[-1]
        if last.final_answer is not None:
            return True
        if self.current_step >= self.max_steps:
            return True
        return False

    @property
    def last_answer(self) -> str:
        """最后一步的答案（final_answer 或 thought）。"""
        if not self.steps:
            return ""
        last = self.steps[-1]
        return last.final_answer or last.thought

    def add_step(self, record: StepRecord) -> None:
        """
        追加一步记录。

        参数：
            record: 新的一步记录（不可变对象）

        副作用：
            修改 self.steps（追加一条记录）
        """
        self.steps.append(record)

    def build_scratchpad(self, keep_recent: int = 0) -> str:
        """
        将已执行步骤拼接为 scratchpad 文本，供下一轮 LLM 使用。

        参数：
            keep_recent: 保留最近 N 步（0 = 保留全部）。
                         用于长对话截断，防止 context window 溢出。

        返回：
            拼接后的 scratchpad 字符串

        设计决策：
        - 默认 keep_recent=0 保留全部（V3 对话短，不需要截断）
        - keep_recent>0 时只保留最近 N 步，并在前面加摘要提示
        - 类比 Java：类似 Logback 的 SizeAndTimeBasedRollingPolicy
        """
        steps_to_show = self.steps
        if keep_recent > 0 and len(steps_to_show) > keep_recent:
            skipped = len(steps_to_show) - keep_recent
            steps_to_show = steps_to_show[-keep_recent:]
            prefix = f"（已省略前 {skipped} 步，仅保留最近 {keep_recent} 步）\n\n"
        else:
            prefix = ""

        return prefix + "".join(s.to_scratchpad_line() for s in steps_to_show)

    def to_dict(self) -> dict[str, Any]:
        """
        将状态序列化为普通 dict（用于 JSON 序列化/trace 输出）。

        类比 Java：类似 Jackson ObjectMapper.writeValueAsString()
        """
        return {
            "question": self.question,
            "model": self.model,
            "max_steps": self.max_steps,
            "current_step": self.current_step,
            "is_finished": self.is_finished,
            "steps": [
                {
                    "step": s.step,
                    "thought": s.thought,
                    "action": s.action,
                    "action_input": s.action_input,
                    "observation": s.observation,
                    "final_answer": s.final_answer,
                }
                for s in self.steps
            ],
        }


# =====================================================================
# 3. StateManager — 状态管理器
# =====================================================================
@dataclass
class StateManager:
    """
    管理对话生命周期：创建状态、更新状态、获取历史。

    类比 Java：
    - 类似 Spring 的 SessionManager
    - 类似 Redux 的 Store（dispatch action → 更新 state）

    职责：
    1. 创建新的 AgentState
    2. 记录每一步的 StepRecord
    3. 提供 build_scratchpad() 给 react_loop 使用
    4. 支持历史截断（keep_recent）

    为什么从 react_loop 中抽出：
    - react_loop 的职责是「循环控制」，不应同时管理状态细节
    - 单一职责：loop 负责 while+终止判断，state 负责历史管理
    - V4 迁移时，StateManager 会被 LangGraph StateGraph 替换
    """
    state: AgentState | None = None

    def start(self, question: str, model: str = "deepseek-chat", max_steps: int = 5) -> AgentState:
        """
        开始一个新的对话会话。

        参数：
            question: 用户问题
            model: 使用的模型名
            max_steps: 最大迭代步数

        返回：
            新创建的 AgentState 对象
        """
        self.state = AgentState(
            question=question,
            model=model,
            max_steps=max_steps,
        )
        return self.state

    def record(self, record: StepRecord) -> None:
        """
        记录一步操作。

        参数：
            record: 新的一步记录

        异常：
            RuntimeError：如果 state 未初始化（需先调用 start()）
        """
        if self.state is None:
            raise RuntimeError("StateManager 未初始化，请先调用 start()")
        self.state.add_step(record)

    def scratchpad(self, keep_recent: int = 0) -> str:
        """
        获取当前 scratchpad 文本。

        参数：
            keep_recent: 保留最近 N 步（0 = 全部）

        返回：
            拼接后的 scratchpad 字符串
        """
        if self.state is None:
            return ""
        return self.state.build_scratchpad(keep_recent=keep_recent)

    @property
    def is_finished(self) -> bool:
        """当前会话是否已终止。"""
        return self.state.is_finished if self.state else False

    @property
    def answer(self) -> str:
        """获取最终答案。"""
        return self.state.last_answer if self.state else ""
