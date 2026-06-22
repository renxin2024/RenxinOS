"""
trace.py — Pipeline 调用链追踪模块

每次 /chat 请求，记录每个子步骤的：
  - 函数名
  - 输入参数（精简版，不存大段原文）
  - 输出摘要（条数、分数范围等，不存完整内容）
  - 耗时（ms）
  - 时间戳

追踪记录追加写入 data/traces.jsonl（每行一条 trace，一个 trace 含多个 step）。
HTML 可视化页面从该文件读取。

类比 Java：类似 Micrometer + Zipkin 的轻量版——
  Micrometer 负责埋点采集，Zipkin 负责可视化展示。
  这里我们用一个 .jsonl 文件 + 一个 .html 页面代替。
"""

import json
import os
import time
import uuid
from pathlib import Path
from datetime import datetime

# traces 文件路径：每行一条完整的 trace（一个 /chat 请求）
TRACES_PATH = Path(os.getenv("RENXINOS_TRACES_PATH", "/tmp/renxinos_traces.jsonl"))

# 当前请求的 trace 上下文（模块级变量，单线程用）
# 类比 Java：类似 ThreadLocal<TraceContext>，每个请求有自己的 trace
_current_trace: dict | None = None


def start_trace(query: str) -> dict:
    """
    开始一次新的 trace。
    在 ask_agent_with_meta 入口处调用。

    参数:
        query: 用户原始问题

    返回:
        trace 上下文字典，后续 log_step 会往里面追加步骤
    """
    global _current_trace
    _current_trace = {
        "trace_id": uuid.uuid4().hex[:8],       # 短 ID，方便在 HTML 中展示
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "query": query,
        "steps": [],                             # 每个子步骤的记录
    }
    return _current_trace


def log_step(
    step_name: str,
    input_summary: dict,
    output_summary: dict,
    elapsed_ms: float,
):
    """
    记录一个子步骤的输入输出。

    参数:
        step_name: 步骤名称（如 "keyword_retrieve", "embedding_retrieve"）
        input_summary: 输入参数摘要（精简，不含大段文本）
        output_summary: 输出结果摘要（条数、分数范围等）
        elapsed_ms: 该步骤耗时（毫秒）

    类比 Java：类似 log.info() + MDC.put()，但结构化存储，不是纯文本日志。
    """
    if _current_trace is None:
        # 没有 trace 上下文时静默跳过（比如测试环境没调用 start_trace）
        return

    _current_trace["steps"].append({
        "step": step_name,
        "input": input_summary,
        "output": output_summary,
        "elapsed_ms": round(elapsed_ms, 1),
    })


def end_trace(final_output: dict):
    """
    结束当前 trace，追加写入 traces.jsonl。

    参数:
        final_output: ask_agent_with_meta 的最终返回值（answer + sources + timings）

    写入格式：JSONL（每行一个完整 JSON），方便后续按行读取和追加。
    类比 Java：类似 Kafka 的 append-only log，只追加不修改。
    """
    global _current_trace
    if _current_trace is None:
        return

    _current_trace["output"] = {
        "answer_length": len(final_output.get("answer", "")),
        "source_count": len(final_output.get("sources", [])),
        "timings": final_output.get("timings", {}),
    }

    # 追加写入（mode="a"），不覆盖历史 trace
    with open(TRACES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(_current_trace, ensure_ascii=False) + "\n")

    _current_trace = None


def load_traces(limit: int = 50) -> list[dict]:
    """
    从 traces.jsonl 读取最近的 trace 记录。

    参数:
        limit: 最多返回几条（从最新往前取）

    返回:
        trace 列表，最新在前
    """
    if not TRACES_PATH.exists():
        return []

    with open(TRACES_PATH, encoding="utf-8") as f:
        lines = f.readlines()

    # 从后往前取 limit 条，再反转（最新在前）
    recent = lines[-limit:]
    traces = [json.loads(line) for line in recent]
    traces.reverse()
    return traces
