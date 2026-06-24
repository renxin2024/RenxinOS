#!/usr/bin/env python3
"""
Renxin OS — V3 S6 CLI demo 入口

提供两种运行模式：
1. 单问题模式：python -m src.agent_raw.main "你的问题"
2. 交互式 REPL 模式：python -m src.agent_raw.main -i

设计决策：
- 不引入 argparse 等第三方 CLI 库（V3 手写理解原理）
- 用 sys.argv 简单解析，保持轻量
- 类比 Java：类似一个简单的 main() 方法，解析 args 后调用核心逻辑

V3→V4 对比：
- V3：命令行参数 → 手动解析 → 调用 run_react()
- V4：FastAPI + uvicorn → HTTP 接口 → 调用 LangGraph agent
"""

from __future__ import annotations

import sys
import os

# 确保项目根在 Python path 中（支持从任意目录运行）
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from src.agent_raw.react_loop import run_react, DEFAULT_MODEL
from src.agent_raw.tools import create_default_registry, create_registry_with_retriever


# =====================================================================
# Demo 问题集（验证「问原则 + 查任务」场景）
# =====================================================================
DEMO_QUESTIONS = [
    "GTD 任务 checkbox 可以写在哪里？今天主块是什么？",
    "计划执行防护规则中，主块的时间段是什么？今天有什么紧急 deadline？",
    "Agent 委派判定标准是什么？我今天的副块任务是什么？",
]

# 默认示例问题（无参数时使用）
DEFAULT_QUESTION = DEMO_QUESTIONS[0]


def print_banner() -> None:
    """打印 CLI 欢迎信息。"""
    print("""
╔══════════════════════════════════════════════╗
║         Renxin OS — V3 ReAct Agent          ║
║   手写 ReAct + function calling + State     ║
║   Tools: search_notes + search_tasks         ║
║   Model: {model:<33}║
╚══════════════════════════════════════════════╝
""".format(model=DEFAULT_MODEL).strip())


def run_single(question: str, max_steps: int = 5, use_mock: bool = False) -> None:
    """
    单问题模式：运行一次 ReAct 循环并输出结果。

    参数：
        question: 用户问题
        max_steps: 最大步数
        use_mock: 是否使用 mock 工具（测试用）
    """
    registry = create_default_registry() if use_mock else create_registry_with_retriever()
    tool_mode = "mock" if use_mock else "真实检索"

    print(f"\n📝 问题：{question}")
    print(f"🔧 工具模式：{tool_mode} | 🔄 最大步数：{max_steps}\n")

    try:
        answer = run_react(question, max_steps=max_steps, verbose=True, registry=registry)
        print(f"\n{'='*50}")
        print(f"✅ 最终答案：\n{answer}")
    except Exception as e:
        print(f"\n❌ 运行出错：{e}")
        import traceback
        traceback.print_exc()


def run_interactive(max_steps: int = 5, use_mock: bool = False) -> None:
    """
    交互式 REPL 模式：循环读取用户输入，逐条执行。

    参数：
        max_steps: 每次查询的最大步数
        use_mock: 是否使用 mock 工具
    """
    registry = create_default_registry() if use_mock else create_registry_with_retriever()
    tool_mode = "mock" if use_mock else "真实检索"

    print_banner()
    print(f"🔧 工具模式：{tool_mode} | 🔄 每次最大步数：{max_steps}")
    print("💡 输入 'exit' 或 'quit' 退出 | 'demo' 运行示例问题\n")

    while True:
        try:
            question = input("🤖 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not question:
            continue
        if question.lower() in ("exit", "quit", "q"):
            print("👋 再见！")
            break
        if question.lower() == "demo":
            print("\n📋 运行示例问题集：")
            for i, q in enumerate(DEMO_QUESTIONS, 1):
                print(f"  {i}. {q}")
            print()
            continue

        print()
        try:
            answer = run_react(question, max_steps=max_steps, verbose=True, registry=registry)
            print(f"\n✅ 答案：{answer}\n")
        except Exception as e:
            print(f"\n❌ 出错：{e}\n")


def main() -> None:
    """
    命令行入口。

    用法：
        python -m src.agent_raw.main                  # 默认示例问题
        python -m src.agent_raw.main "你的问题"        # 单问题模式
        python -m src.agent_raw.main -i                # 交互式 REPL
        python -m src.agent_raw.main -i --mock         # REPL + mock 工具
        python -m src.agent_raw.main --steps 3 "问题"  # 自定义最大步数

    类比 Java：类似 public static void main(String[] args)
    """
    args = sys.argv[1:]

    # 解析参数
    interactive = False
    use_mock = False
    max_steps = 5
    question_parts: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-i", "--interactive"):
            interactive = True
        elif arg in ("--mock", "-m"):
            use_mock = True
        elif arg in ("--steps", "-s"):
            i += 1
            if i < len(args):
                try:
                    max_steps = int(args[i])
                except ValueError:
                    print(f"⚠ 无效步数：{args[i]}，使用默认值 5")
        elif arg in ("-h", "--help"):
            print(__doc__)
            print("用法：python -m src.agent_raw.main [选项] [问题]")
            print("选项：")
            print("  -i, --interactive  交互式 REPL 模式")
            print("  -m, --mock         使用 mock 工具（无需真实数据）")
            print("  -s, --steps N      最大步数（默认 5）")
            print("  -h, --help         显示此帮助")
            return
        else:
            question_parts.append(arg)
        i += 1

    question = " ".join(question_parts) if question_parts else ""

    if interactive:
        run_interactive(max_steps=max_steps, use_mock=use_mock)
    else:
        if not question:
            question = DEFAULT_QUESTION
            print(f"💡 未指定问题，使用默认示例：{question}")
        print_banner()
        run_single(question, max_steps=max_steps, use_mock=use_mock)


if __name__ == "__main__":
    main()
