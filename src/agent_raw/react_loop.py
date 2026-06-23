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
from dataclasses import dataclass, field
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path as _Path
import json as _json
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

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

    返回：
        最终答案字符串

    副作用：
        每次调用会将完整 trace（prompt / raw_output / observation）
        追加写入 data/react_traces.jsonl，供 react_trace_viewer 展示。
    """
    # 如果没有传入 registry，默认使用带真实检索的注册表
    # 类比 Java：类似 Optional.ofNullable(registry).orElseGet(() -> createRegistry())
    if registry is None:
        registry = create_registry_with_retriever()

    scratchpad = ""  # 记录 Thought/Action/Observation 历史，类似草稿本
    # trace 记录：每个 step 的完整 LLM 交互
    trace_steps = []
    trace_id = _json.loads(f'{{"t": {int(__import__("time").time())}}}')["t"]

    if verbose:
        console.print(Panel(f"[bold]{question}[/bold]", title="[bold blue]🤖 ReAct Agent Start[/bold blue]", subtitle=f"model={DEFAULT_MODEL}, max_steps={max_steps}", border_style="blue"))

    for step in range(1, max_steps + 1):
        prompt = build_react_prompt(question, scratchpad, registry)
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            # stop 序列：模型生成到 "Observation:" 时立即截断，
            # 防止模型自己编造工具返回结果（文本 ReAct 的经典问题）
            stop=["Observation:"],
        )
        raw_output = response.choices[0].message.content or ""
        parsed = parse_llm_output(raw_output)

        if verbose:
            console.print(f"\n[bold cyan]═══ Step {step} ═══[/bold cyan]")
            console.print(Panel(parsed.thought, title="[bold]💭 Thought[/bold]", border_style="yellow"))
            if parsed.action:
                console.print(f"[bold]🔧 Action:[/bold] [orange1]{parsed.action}[/orange1]")
                console.print(f"[bold]📥 Action Input:[/bold] {parsed.action_input or '(empty)'}")
            if parsed.final_answer:
                console.print(Panel(parsed.final_answer, title="[bold green]✅ Final Answer[/bold green]", border_style="green"))

        # 收集本步 trace
        step_trace = {
            "step": step,
            "prompt": prompt,
            "raw_output": raw_output,
            "thought": parsed.thought,
            "action": parsed.action,
            "action_input": parsed.action_input,
            "final_answer": parsed.final_answer,
            "observation": None,
        }

        # 终止条件 1：模型主动给出 Final Answer
        if parsed.final_answer is not None:
            trace_steps.append(step_trace)
            _save_trace(trace_id, question, trace_steps, parsed.final_answer)
            return parsed.final_answer

        # 终止条件 2：模型没产生可执行动作，把 thought 当答案返回
        if parsed.action is None:
            step_trace["observation"] = "（未检测到 Action，返回 thought）"
            trace_steps.append(step_trace)
            _save_trace(trace_id, question, trace_steps, parsed.thought)
            if verbose:
                print("未检测到 Action，返回当前思考内容。")
            return parsed.thought

        # 执行 tool：使用 ToolRegistry.execute() 替代直接调用
        # 同时支持 parse_tool_call 的结构化解析（S2 新增）
        tool_call = parse_tool_call(raw_output)
        if tool_call and tool_call.tool_name:
            # 结构化解析成功，用 arguments dict 调用
            observation = registry.execute(tool_call.tool_name, **tool_call.arguments)
            # 同步 parsed.action 供 scratchpad 和 verbose 使用
            if parsed.action is None:
                parsed = ParseResult(
                    thought=parsed.thought,
                    action=tool_call.tool_name,
                    action_input=str(tool_call.arguments),
                )
        elif parsed.action:
            # 文本 ReAct 格式（S1 兼容），用 action + action_input 调用
            observation = registry.execute(parsed.action, query=parsed.action_input or "")
        else:
            observation = "错误：无法解析出工具调用。" 

        step_trace["observation"] = observation
        trace_steps.append(step_trace)

        if verbose:
            console.print(Panel(observation, title=f"[bold]📤 Observation ({parsed.action})[/bold]", border_style="green"))

        # 把本步结果追加到 scratchpad，供下一轮 LLM 看到完整上下文
        scratchpad += (
            f"Thought: {parsed.thought}\n"
            f"Action: {parsed.action}\n"
            f"Action Input: {parsed.action_input or ''}\n"
            f"Observation: {observation}\n"
        )

    # 终止条件 3：超过最大步数，返回最后思考内容
    if verbose:
        console.print(f"\n[bold red]⚠ 达到最大步数 {max_steps}[/bold red]，返回最后思考内容。")
    _save_trace(trace_id, question, trace_steps, parsed.thought)
    return parsed.thought


def _save_trace(trace_id: int, question: str, steps: list, final_answer: str):
    """将本次 run_react 的完整 trace 追加写入 JSONL。"""
    record = {
        "trace_id": trace_id,
        "question": question,
        "model": DEFAULT_MODEL,
        "steps": steps,
        "final_answer": final_answer,
    }
    with open(TRACE_PATH, "a", encoding="utf-8") as f:
        f.write(_json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\n[trace] 已保存至 {TRACE_PATH}（trace_id={trace_id}）")


# =====================================================================
# 5. S1 最小可运行示例
# =====================================================================
if __name__ == "__main__":
    # S2+S3：使用真实检索注册表（search_notes 接 V2 retrieve_hybrid）
    # 测试 mock 可改用 create_default_registry()
    test_question = "GTD 任务 checkbox 可以写在哪里？今天主块是什么？"
    print(f"问题：{test_question}\n")
    answer = run_react(test_question, max_steps=3, verbose=True)
    print(f"\n最终答案：\n{answer}")
