#!/usr/bin/env python3
"""
Renxin OS — V3 S1 ReAct loop 骨架

手写 ReAct（Reasoning + Acting）循环：
- 让模型显式输出 "Thought / Action / Action Input"
- 框架解析后调用对应 tool，再把结果以 "Observation" 拼回 prompt
- 循环直到模型输出 "Final Answer" 或达到最大步数

本文件是 S1 骨架，tool 先用 mock；S2–S4 会换成真实实现。
"""

import os
import re
import time as _time
from dataclasses import dataclass, field
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path as _Path
import json as _json
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich import box

console = Console()

# trace 记录路径：每次 run_react 的完整 LLM 交互链
TRACE_DIR = _Path(__file__).resolve().parents[2] / "data"
TRACE_DIR.mkdir(exist_ok=True)
TRACE_PATH = TRACE_DIR / "react_traces.jsonl"


# 加载 .env 中的 API key / base_url / model
# 类比 Java：类似 Spring 的 @Value 从 application.properties 注入配置
load_dotenv()

# V3 agent_raw 使用 DeepSeek 官方 API（与 V2 DashScope 分离）
# 用户手动填写 DEEPSEEK_API_KEY，默认模型为 deepseek-chat（即 DeepSeek-V3）
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
)
DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


# =====================================================================
# 1. 工具注册（S2：从 tools.py 导入结构化定义 + 注册表）
# =====================================================================
from src.agent_raw.tools import (
    ToolRegistry,       # 工具注册表（类比 Spring ApplicationContext）
    ToolCall,           # 工具调用解析结果
    parse_tool_call,    # 从 LLM 输出解析工具调用
    format_observation, # 格式化工具返回值为 Observation 文本
    create_default_registry,       # mock 工具注册（测试用）
    create_registry_with_retriever,# 真实检索注册（S3 使用）
)

# S5：State dict + 对话历史管理
from src.agent_raw.state import (
    StepRecord,     # 单步操作的不可变记录
    StateManager,   # 状态管理器（管理对话生命周期）
)


# =====================================================================
# 2. ReAct prompt 模板
# =====================================================================
def build_react_prompt(question: str, scratchpad: str, registry: ToolRegistry) -> str:
    """
    构造 ReAct 格式的完整 prompt。

    参数：
        question: 用户原始问题
        scratchpad: 已经执行过的 Thought/Action/Observation 历史

    返回：
        可直接送入 LLM 的 prompt 字符串
    """
    # 从 registry 获取工具描述（结构化 schema，而非简单 name: desc）
    tool_descs = registry.format_all_for_prompt()
    tool_names = ", ".join(registry.tool_names)

    # scratchpad 为空时，模型从 Thought 开始续写；
    # scratchpad 非空时，把历史步骤拼进来，让模型看到之前的观察和当前状态。
    return f"""你是一个会逐步思考的助手。请按 ReAct 格式回答问题。

可用工具：
{tool_descs}

重要规则：
- 你必须先调用工具获取信息，禁止在第一轮直接给出 Final Answer
- 只有在获得 Observation 之后，才可以给出 Final Answer
- 禁止仅凭自身知识回答，所有回答必须基于工具检索到的内容
- 如果 Observation 已包含足够回答问题的信息，请立即给出 Final Answer，不要继续调用工具
- 如果问题包含多个子问题，尽量在同一轮用一个综合查询获取所有需要的信息
- 如果前一步搜索未命中，最多再尝试 1 次换词搜索，仍无结果则基于已有信息回答

请严格使用以下格式（每一步只输出 Thought + Action + Action Input，或最终答案）：

Question: 需要回答的问题
Thought: 思考当前应该做什么
Action: 要调用的工具名，必须是 [{tool_names}] 之一
Action Input: 传给工具的输入
Observation: 工具返回的结果
...（Thought/Action/Action Input/Observation 可重复多轮）
Thought: 我现在可以给出最终答案
Final Answer: 对原问题的最终回答

开始！

Question: {question}
{scratchpad}Thought:
"""


# =====================================================================
# 3. 解析 LLM 输出
# =====================================================================
@dataclass
class ParseResult:
    """
    解析一次 LLM 输出的结果。

    字段：
        thought: 模型的思考内容
        action: 要调用的工具名（仅当需要继续循环时）
        action_input: 传给工具的输入（仅当需要继续循环时）
        final_answer: 最终答案（仅当循环可终止时）
    """
    thought: str
    action: str | None = None
    action_input: str | None = None
    final_answer: str | None = None


def parse_llm_output(text: str) -> ParseResult:
    """
    从模型输出中解析 Thought、Action、Action Input 或 Final Answer。

    支持两种结束形态：
    1. 继续循环：输出 Action / Action Input
    2. 终止循环：输出 Final Answer
    """
    text = text.strip()

    # 先尝试提取 Final Answer：一旦出现，立即结束循环
    final_match = re.search(r"Final Answer:\s*(.+)", text, re.DOTALL)
    if final_match:
        return ParseResult(
            thought=_extract_thought(text),
            final_answer=final_match.group(1).strip(),
        )

    # 再尝试提取 Action / Action Input，继续循环
    action_match = re.search(r"Action:\s*(\w+)", text)
    action_input_match = re.search(
        r"Action Input:\s*(.+?)(?:\nObservation:|$)", text, re.DOTALL
    )
    if action_match:
        return ParseResult(
            thought=_extract_thought(text),
            action=action_match.group(1).strip(),
            action_input=action_input_match.group(1).strip() if action_input_match else "",
        )

    # 兜底：没匹配到 Action 也没 Final Answer，只返回 thought
    # 外层可选择用 thought 作为最终答案或报错
    return ParseResult(thought=text)


def _extract_thought(text: str) -> str:
    """提取 Thought: 后面的内容。"""
    match = re.search(
        r"Thought:\s*(.+?)(?:\nAction:|\nFinal Answer:|$)", text, re.DOTALL
    )
    if match:
        return match.group(1).strip()
    return text.strip()


def _build_fallback_answer(thought: str, manager) -> str:
    """
    兜底答案生成：当模型未产出有效 thought/final_answer 时，
    从已执行的检索步骤中提取 observation 内容，拼接为答案。

    触发场景（S7 修复 #2 空答案问题）：
    - 模型返回空响应（API 异常、格式错误）
    - 模型只输出了 thought 但未给出 Action 或 Final Answer
    - thought 为空但前面步骤已有检索结果

    策略：
    1. 如果 thought 非空 → 直接返回 thought（原有行为）
    2. 如果 thought 为空但有历史 observation → 提取前一步 observation 的前 500 字
    3. 如果都没有 → 返回通用兜底消息

    类比 Java：类似 try-catch 中的 fallback 逻辑，保证用户体验不中断
    """
    if thought and thought.strip():
        return thought.strip()

    # 从已执行的步骤中提取最后一条 observation
    steps = manager.state.steps if manager.state else []
    for s in reversed(steps):
        if s.observation and s.observation.strip():
            obs = s.observation.strip()
            # 截取前 500 字，避免 observation 过长
            snippet = obs[:500]
            return (
                f"抱歉，模型在处理时未生成完整回答。以下是从检索结果中自动提取的相关信息：\n\n"
                f"{snippet}"
                f"{'...' if len(obs) > 500 else ''}\n\n"
                f"（这是自动生成的兜底答案，请查看上方 Observation 获取完整检索结果。）"
            )

    return "抱歉，模型未能生成有效回答，且没有可用的检索结果。请重试或简化问题。"


# =====================================================================
# 3.5 步骤日志（S7 新增 — 统一格式化每步 Thought/Action/Observation）
# =====================================================================
def log_step_header(step: int, total: int, elapsed_ms: float | None = None) -> None:
    """
    打印步骤头部（Step N/M + 累计耗时）。

    设计意图：
    - 用分隔线清晰区分每一步，避免 Thought/Action/Observation 混在一起
    - 时间戳让用户感知 LLM 调用的延迟（这是 Agent 的主要性能瓶颈）
    - 类比 Java：类似 log.info("=== Step {} / {} ===", step, maxSteps)
    """
    time_str = f" | ⏱ 累计 {elapsed_ms/1000:.1f}s" if elapsed_ms else ""
    console.rule(f"[bold cyan]Step {step}/{total}{time_str}[/bold cyan]")


def log_thought(thought: str) -> None:
    """
    打印模型的思考过程。

    设计意图：
    - 黄色边框 = "思考阶段"（模型在推理，还没动手）
    - Panel 包裹让长文本不被终端截断破坏可读性
    - 类比：Java 中这是 log.debug("Agent thought: {}") 的 rich 可视化版本
    """
    console.print(Panel(
        thought,
        title="[bold yellow]💭 Thought[/bold yellow]",
        title_align="left",
        border_style="yellow",
    ))


def log_action(action: str, action_input: str) -> None:
    """
    打印工具调用决策。

    设计意图：
    - 橙色 = "执行阶段"（模型决定调用工具了）
    - Action 和 Action Input 分行，方便复制调试
    - 类比：Java 中这是 log.info("Calling tool: {} with args: {}")
    """
    console.print(f"[bold orange1]🔧 Action:[/bold orange1] {action}")
    if action_input:
        console.print(f"[dim]   📥 Input: {action_input}[/dim]")


def log_observation(observation: str, tool_name: str, tool_elapsed_ms: float) -> None:
    """
    打印工具返回的观察结果。

    设计意图：
    - 绿色边框 = "观察阶段"（模型收到了外部反馈）
    - 显示工具耗时，帮助发现慢工具（如检索耗时过长）
    - 类比：Java 中这是 log.info("Tool {} returned in {}ms: {}")
    """
    console.print(Panel(
        observation,
        title=f"[bold green]📤 Observation ({tool_name}) ⏱ {tool_elapsed_ms:.0f}ms[/bold green]",
        title_align="left",
        border_style="green",
    ))


def log_final_answer(answer: str, total_steps: int, total_elapsed_ms: float) -> None:
    """
    打印最终答案与汇总统计。

    设计意图：
    - 绿色 Panel + 统计信息（步数、总耗时）——让用户一眼看到 Agent 完成了什么
    - 类比：Java 中这是最终 log.info("Task completed in {} steps, {}ms") + 输出结果
    """
    console.print(Panel(
        answer,
        title=f"[bold green]✅ Final Answer[/bold green]",
        title_align="left",
        border_style="green",
    ))
    console.print(
        f"[dim]📊 统计：{total_steps} 步 | ⏱ 总耗时 {total_elapsed_ms/1000:.1f}s "
        f"| 平均 {total_elapsed_ms/total_steps/1000:.1f}s/步[/dim]"
    )


def log_max_steps_warning(max_steps: int, last_thought: str) -> None:
    """打印超步数警告。"""
    console.rule("[bold red]⚠ 达到最大步数限制[/bold red]")
    console.print(f"[yellow]最后思考内容：[/yellow]{last_thought[:200]}")


# =====================================================================
# 4. ReAct 主循环
# =====================================================================
def run_react(question: str, max_steps: int = 5, verbose: bool = True, registry: ToolRegistry | None = None) -> str:
    """
    执行 ReAct 循环。

    参数：
        question: 用户问题
        max_steps: 最大迭代步数（防止无限循环）
        verbose: 是否打印每步思考过程
        registry: 工具注册表（None 则使用默认注册表）

    返回：
        最终答案字符串

    副作用：
        每次调用会将完整 trace（prompt / raw_output / observation）
        追加写入 data/react_traces.jsonl，供 react_trace_viewer 展示。

    V3 S5 改进：使用 StateManager 替代字符串 scratchpad。
    - 旧方式：scratchpad = "" → scratchpad += "Thought: ...\n"
    - 新方式：StateManager.record(StepRecord(...)) → manager.scratchpad()
    - 好处：结构化存储、可查询历史、支持截断、为 V4 LangGraph 迁移铺垫
    """
    # 如果没有传入 registry，默认使用带真实检索的注册表
    if registry is None:
        registry = create_registry_with_retriever()

    # S5：使用 StateManager 管理对话历史（替代旧 scratchpad 字符串）
    manager = StateManager()
    state = manager.start(question=question, model=DEFAULT_MODEL, max_steps=max_steps)

    # trace 记录：每个 step 的完整 LLM 交互
    trace_steps = []
    trace_id = _json.loads(f'{{"t": {int(__import__("time").time())}}}')["t"]

    # S7：总计时器（从 Agent 启动到结束的墙钟时间）
    t_start = _time.perf_counter()

    if verbose:
        console.print(Panel(
            f"[bold]{question}[/bold]",
            title="[bold blue]🤖 ReAct Agent Start[/bold blue]",
            subtitle=f"model={DEFAULT_MODEL}, max_steps={max_steps}",
            border_style="blue",
        ))

    for step in range(1, max_steps + 1):
        scratchpad = manager.scratchpad()
        prompt = build_react_prompt(question, scratchpad, registry)

        # S7：记录 LLM 调用耗时
        t_llm_start = _time.perf_counter()
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            stop=["Observation:"],
        )
        llm_elapsed_ms = (_time.perf_counter() - t_llm_start) * 1000
        elapsed_total = (_time.perf_counter() - t_start) * 1000

        raw_output = response.choices[0].message.content or ""
        parsed = parse_llm_output(raw_output)

        # S7：使用统一日志函数替代零散 console.print
        if verbose:
            log_step_header(step, max_steps, elapsed_total)
            log_thought(parsed.thought)

            if parsed.action:
                log_action(parsed.action, parsed.action_input or "")
            if parsed.final_answer:
                log_final_answer(
                    parsed.final_answer,
                    total_steps=step,
                    total_elapsed_ms=elapsed_total,
                )

        # 收集本步 trace（S7：新增时间戳字段 llm_ms / tool_ms / total_ms）
        step_trace = {
            "step": step,
            "prompt": prompt,
            "raw_output": raw_output,
            "thought": parsed.thought,
            "action": parsed.action,
            "action_input": parsed.action_input,
            "final_answer": parsed.final_answer,
            "observation": None,
            # S7 计时字段：让 HTML 查看器能展示每步性能
            "llm_ms": round(llm_elapsed_ms, 1),
            "tool_ms": None,
            "total_ms": round(elapsed_total, 1),
        }

        # 终止条件 1：模型主动给出 Final Answer
        if parsed.final_answer is not None:
            manager.record(StepRecord(
                step=step,
                thought=parsed.thought,
                final_answer=parsed.final_answer,
                raw_output=raw_output,
            ))
            trace_steps.append(step_trace)
            _save_trace(trace_id, question, trace_steps, parsed.final_answer,
                        total_ms=(_time.perf_counter() - t_start) * 1000)
            return parsed.final_answer

        # 终止条件 2：模型没产生可执行动作，把 thought 当答案返回
        if parsed.action is None:
            # S7 兜底增强：如果 thought 为空但已有检索结果，
            # 自动从 observation 提取关键内容拼接为答案，避免返回空字符串。
            fallback_answer = _build_fallback_answer(parsed.thought, manager)
            step_trace["observation"] = "（未检测到 Action，自动拼接待检内容为答案）"
            trace_steps.append(step_trace)
            manager.record(StepRecord(
                step=step,
                thought=parsed.thought,
                final_answer=fallback_answer,
                raw_output=raw_output,
            ))
            _save_trace(trace_id, question, trace_steps, fallback_answer,
                        total_ms=(_time.perf_counter() - t_start) * 1000)
            if verbose:
                if parsed.thought:
                    print("未检测到 Action，返回当前思考内容。")
                else:
                    console.print("[yellow]⚠ 模型未产出有效内容，已从检索结果中自动拼接答案。[/yellow]")
            return fallback_answer

        # 执行 tool（S7：记录工具执行耗时）
        t_tool_start = _time.perf_counter()
        tool_call = parse_tool_call(raw_output)
        if tool_call and tool_call.tool_name:
            observation = registry.execute(tool_call.tool_name, **tool_call.arguments)
            if parsed.action is None:
                parsed = ParseResult(
                    thought=parsed.thought,
                    action=tool_call.tool_name,
                    action_input=str(tool_call.arguments),
                )
        elif parsed.action:
            observation = registry.execute(parsed.action, query=parsed.action_input or "")
        else:
            observation = "错误：无法解析出工具调用。"
        tool_elapsed_ms = (_time.perf_counter() - t_tool_start) * 1000

        step_trace["observation"] = observation
        step_trace["tool_ms"] = round(tool_elapsed_ms, 1)
        step_trace["total_ms"] = round((_time.perf_counter() - t_start) * 1000, 1)
        trace_steps.append(step_trace)

        if verbose:
            log_observation(observation, parsed.action or "unknown", tool_elapsed_ms)

        # S5：使用 StepRecord 记录本步（替代旧 scratchpad += 字符串拼接）
        manager.record(StepRecord(
            step=step,
            thought=parsed.thought,
            action=parsed.action,
            action_input=parsed.action_input or "",
            observation=observation,
            raw_output=raw_output,
        ))

    # 终止条件 3：超过最大步数
    if verbose:
        log_max_steps_warning(max_steps, state.last_answer)
    _save_trace(trace_id, question, trace_steps, state.last_answer,
                total_ms=(_time.perf_counter() - t_start) * 1000)
    return state.last_answer


def _save_trace(trace_id: int, question: str, steps: list, final_answer: str, total_ms: float = 0):
    """将本次 run_react 的完整 trace 追加写入 JSONL。

    S7 新增：记录启动时间戳、总耗时、每步 LLM/工具耗时，
    供 HTML 查看器展示性能摘要。
    """
    record = {
        "trace_id": trace_id,
        "question": question,
        "model": DEFAULT_MODEL,
        "steps": steps,
        "final_answer": final_answer,
        # S7：全局计时与元信息
        "started_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_ms": round(total_ms, 1),
        "total_steps": len(steps),
    }
    with open(TRACE_PATH, "a", encoding="utf-8") as f:
        f.write(_json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\n[trace] 已保存至 {TRACE_PATH}（trace_id={trace_id}）")


# =====================================================================
# 5. 快速测试入口（S6 后推荐使用 main.py CLI）
# =====================================================================
if __name__ == "__main__":
    # 快速测试：直接运行此文件可验证 react_loop 是否正常
    # 完整 CLI 请使用：python -m src.agent_raw.main
    from src.agent_raw.tools import create_default_registry

    test_question = "GTD 任务 checkbox 可以写在哪里？今天主块是什么？"
    print(f"问题：{test_question}\n")
    answer = run_react(test_question, max_steps=3, verbose=True, registry=create_default_registry())
    print(f"\n最终答案：\n{answer}")
