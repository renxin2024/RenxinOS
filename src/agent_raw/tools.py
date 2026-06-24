#!/usr/bin/env python3
"""
Renxin OS — V3 S2 手写 function calling（tool 定义 + 解析）

核心概念：
- ToolDef：工具的结构化定义（名称、描述、参数 schema）
  类比 Java：类似 @WebService 注解声明接口，定义方法名、入参、出参
- TOOL_REGISTRY：所有已注册工具的字典，react_loop 通过它查找并执行工具
  类比 Java：类似 Spring 的 ApplicationContext，按 bean name 查找实现类
- tool_call 解析：从 LLM 输出中提取结构化的工具调用请求
  类比 Java：类似反序列化 JSON → Java 对象，但这里是正则解析

V3 设计决策：
1. 不用 OpenAI SDK 的 tools/functions 参数（那是框架功能，V3 要手写理解原理）
2. 自己定义 schema 格式，手动解析 LLM 输出中的工具调用
3. 保留 S1 的文本 ReAct（Thought/Action/Action Input）作为主路径
4. S3 会把 search_notes 接上 V2 的 retrieve_hybrid()
5. S4 会把 search_tasks 接上 mock 任务池数据
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable


# =====================================================================
# 1. ToolDef — 工具的结构化定义
# =====================================================================
@dataclass
class ToolParamDef:
    """
    单个工具参数的定义。

    类比 Java：类似 @RequestParam 注解 + 类型声明
    - name: 参数名（对应 Java 方法签名中的形参名）
    - type: 参数类型（string / number / boolean / array / object）
    - description: 参数说明（告诉 LLM 这个参数是什么意思）
    - required: 是否必填（类比 @RequestParam(required=true)）
    - enum: 可选值列表（类比 @Pattern + 枚举约束）
    """
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    enum: list[str] | None = None


@dataclass
class ToolDef:
    """
    工具的完整定义。

    类比 Java：类似一个 Interface 声明，包含：
    - 方法名 (name)
    - 方法说明 (description) — 告诉 LLM 什么时候该调用这个工具
    - 参数列表 (parameters) — 方法的入参定义
    - 实现函数 (fn) — 实际执行的逻辑

    在 V3（手写版），我们把 schema 定义和执行函数绑定在同一个对象里。
    在 V4（框架版），这会被拆成 LangChain @tool decorator + MCP 协议。
    """
    name: str
    description: str
    parameters: list[ToolParamDef]
    fn: Callable[..., str]

    def schema_dict(self) -> dict:
        """
        生成类似 OpenAI function calling 的 schema 字典。

        返回格式和 OpenAI API 的 tools[].function 一致，
        这样在 V4 切换框架时，schema 可以直接复用。

        类比 Java：类似把 Java 接口定义序列化为 OpenAPI/Swagger JSON
        """
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def format_for_prompt(self) -> str:
        """
        生成给 LLM prompt 的工具描述文本。

        V3 用纯文本格式（ReAct 风格）告诉模型有哪些工具可用。
        V4 会用 OpenAI API 的 tools 参数自动注入。

        类比 Java：类似把接口文档打印出来给调用方看
        """
        params_desc = ", ".join(
            f"{p.name}({p.type}): {p.description}"
            + (" [必填]" if p.required else " [可选]")
            + (f" 可选值={p.enum}" if p.enum else "")
            for p in self.parameters
        )
        return f"{self.name}({params_desc}) — {self.description}"


# =====================================================================
# 2. ToolRegistry — 工具注册表
# =====================================================================
class ToolRegistry:
    """
    工具注册表：管理所有可用的工具定义和执行函数。

    类比 Java：
    - 类似 Spring 的 ApplicationContext：按 name 查找 bean
    - 类似 Java 的 ServiceLoader：运行时发现和加载服务实现

    为什么不用简单的 dict：
    - 需要同时按名称查找 ToolDef（含 schema）和执行函数
    - 需要批量生成 prompt 文本和 schema 列表
    - 统一入口方便后续扩展（权限控制、调用计数等）
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        """注册一个工具。同名工具会被覆盖（类似 Map.put）。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        """按名称查找工具定义。找不到返回 None（类似 Map.get）。"""
        return self._tools.get(name)

    def execute(self, name: str, **kwargs: Any) -> str:
        """
        执行指定工具。

        参数：
            name: 工具名
            **kwargs: 传给工具函数的关键字参数

        返回：
            工具执行结果（字符串，会作为 Observation 喂回 LLM）

        异常：
            如果工具不存在，返回错误提示字符串（不抛异常，让 Agent 能继续推理）

        类比 Java：类似 ApplicationContext.getBean(name).execute(args)
        """
        tool = self._tools.get(name)
        if tool is None:
            available = list(self._tools.keys())
            return f"错误：未知工具 '{name}'，可用工具为 {available}。"
        try:
            return tool.fn(**kwargs)
        except Exception as e:
            return f"工具 '{name}' 执行出错：{e}"

    @property
    def tool_names(self) -> list[str]:
        """所有已注册工具的名称列表。"""
        return list(self._tools.keys())

    def format_all_for_prompt(self) -> str:
        """
        生成给 LLM prompt 的完整工具描述列表。

        类比 Java：类似把所有 REST API 的 Swagger 文档拼成一页
        """
        return "\n".join(
            f"  {i+1}. {tool.format_for_prompt()}"
            for i, tool in enumerate(self._tools.values())
        )

    def schemas_list(self) -> list[dict]:
        """
        生成所有工具的 schema 字典列表（兼容 OpenAI 格式）。

        V4 会直接用这个列表传给 LangChain @tool 或 OpenAI API。
        """
        return [tool.schema_dict() for tool in self._tools.values()]


# =====================================================================
# 3. tool_call 解析
# =====================================================================
@dataclass
class ToolCall:
    """
    一次工具调用的解析结果。

    类比 Java：类似反序列化后的请求对象
    - tool_name: 要调哪个工具（对应 Spring 的 bean name）
    - arguments: 传给工具的参数（对应方法实参）
    - raw_text: LLM 的原始输出（保留用于调试和 trace）
    """
    tool_name: str
    arguments: dict[str, Any]
    raw_text: str = ""


def parse_tool_call(text: str) -> ToolCall | None:
    """
    从 LLM 输出中解析出工具调用。

    V3 支持两种格式（兼容不同模型的输出习惯）：

    格式 1 — 文本 ReAct 风格（S1 已有）：
        Action: search_notes
        Action Input: GTD checkbox 写在哪

    格式 2 — 类 JSON function calling 风格（S2 新增）：
        ```tool_call
        {"name": "search_notes", "arguments": {"query": "GTD checkbox 写在哪"}}
        ```

    设计意图：
    - 格式 1 是 ReAct 论文的标准格式，所有文本 LLM 都支持
    - 格式 2 模拟 OpenAI function calling 的结构化输出，
      让 LLM 以 JSON 格式输出工具调用，解析更可靠
    - 两种格式共存，V3 先跑通格式 1，格式 2 作为进阶练习

    类比 Java：
    - 格式 1 像解析 HTTP query string（?action=search&input=GTD）
    - 格式 2 像解析 JSON request body（{"action":"search","input":"GTD"}）
    - 两种都能工作，但 JSON 格式更结构化、更不容易解析出错
    """
    text = text.strip()

    # --- 格式 2：类 JSON function calling ---
    # 匹配 ```tool_call ... ``` 或 ```json ... ``` 包裹的 JSON 块
    json_block_match = re.search(
        r"```(?:tool_call|json)\s*\n?(.*?)\n?\s*```",
        text,
        re.DOTALL,
    )
    if json_block_match:
        json_str = json_block_match.group(1).strip()
        try:
            data = json.loads(json_str)
            tool_name = data.get("name", "")
            arguments = data.get("arguments", {})
            if tool_name:
                return ToolCall(
                    tool_name=tool_name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    raw_text=text,
                )
        except json.JSONDecodeError:
            pass  # JSON 解析失败，回退到格式 1

    # --- 格式 2b：裸 JSON（无代码块包裹）---
    # 有些模型可能直接输出 {"name": "...", "arguments": {...}} 而不加 ``` 包裹
    # 策略：如果文本以 { 开头，尝试直接 json.loads 解析整个文本
    # 比正则匹配更可靠——正则 \{[^}]*\} 无法处理嵌套大括号
    if text.startswith("{") and "name" in text:
        try:
            data = json.loads(text)
            tool_name = data.get("name", "")
            arguments = data.get("arguments", {})
            if tool_name and isinstance(arguments, dict):
                return ToolCall(
                    tool_name=tool_name,
                    arguments=arguments,
                    raw_text=text,
                )
        except json.JSONDecodeError:
            pass

    # --- 格式 1：文本 ReAct 风格 ---
    action_match = re.search(r"Action:\s*(\w+)", text)
    action_input_match = re.search(
        r"Action Input:\s*(.+?)(?:\nObservation:|$)", text, re.DOTALL
    )

    if action_match:
        tool_name = action_match.group(1).strip()
        action_input = action_input_match.group(1).strip() if action_input_match else ""

        # 文本格式只有一个字符串参数，按约定映射到第一个参数名
        # 大多数工具的第一个参数就是 query，所以直接用 "query" 作为 key
        # 如果工具的第一个参数不叫 query，这里需要调整
        arguments = {"query": action_input} if action_input else {}

        return ToolCall(
            tool_name=tool_name,
            arguments=arguments,
            raw_text=text,
        )

    # 没有匹配到任何工具调用格式
    return None


def format_observation(observation: str, tool_name: str = "") -> str:
    """
    将工具执行结果格式化为 Observation 文本，供拼回 LLM prompt。

    参数：
        observation: 工具返回的结果字符串
        tool_name: 工具名（可选，用于标注来源）

    类比 Java：类似把 Service 返回值序列化为响应 JSON
    """
    prefix = f"[{tool_name}]" if tool_name else "[工具结果]"
    # 截断过长结果，避免 prompt 膨胀
    max_len = 1500
    if len(observation) > max_len:
        observation = observation[:max_len] + f"…（共 {len(observation)} 字，已截断）"
    return f"{prefix} {observation}"


# =====================================================================
# 4. 内置工具实现（S3 会替换 search_notes 的 mock 实现）
# =====================================================================

def _mock_search_notes(query: str) -> str:
    """
    模拟查笔记工具（S1 占位）。

    S3 会替换为调用 V2 的 retrieve_hybrid()，实现真实的笔记检索。
    保留此函数作为 fallback：如果检索模块加载失败，降级为 mock。
    """
    return (
        f"【模拟笔记检索结果】查询词：{query}\n"
        "1. GTD 任务 checkbox 只允许写在「全局任务池」和「projects/」下；\n"
        "2. 日志只写总结，不改任务状态。"
    )


def _mock_search_tasks(query: str) -> str:
    """
    模拟查任务池工具（S1 占位，已废弃）。

    S4 已替换为 _real_search_tasks()，此函数保留作为 fallback。
    """
    return (
        f"【模拟任务池结果】查询词：{query}\n"
        "- 今日主块：V3 S2 function calling\n"
        "- 今日副块：read30《原则》第 4 章"
    )


def _real_search_tasks(query: str) -> str:
    """
    真实的查任务池工具（S4 实现）。

    从 tasks/全局任务池.md 中解析「📍 一眼行动」和「☀️ 今日执行」两节，
    提取今日任务、主块、副块、deadline 等关键信息。

    参数：
        query: 检索查询词（如「今天主块」「deadline」「紧急任务」）

    返回：
        格式化的任务信息文本，供 LLM 阅读

    设计决策：
    - 不使用第三方 Markdown 解析库（V3 手写理解原理）
    - 用正则解析固定结构（一眼行动表格 + Day Planner 清单）
    - 任务池路径通过环境变量 TODO_DIR 注入，默认相对于 RenxinOS 项目根

    类比 Java：
    - 类似用 Scanner/BufferedReader 手动解析配置文件
    - 而非用 Spring 的 @ConfigurationProperties 自动绑定
    """
    import os as _os
    from pathlib import Path

    # 任务池路径：默认 ../todo/tasks/全局任务池.md（相对于 RenxinOS 根）
    todo_dir = _os.getenv("TODO_DIR", "")
    if todo_dir:
        tasks_pool_path = Path(todo_dir) / "tasks" / "全局任务池.md"
    else:
        # 从 RenxinOS 项目根向上找 todo 目录
        renxinos_root = Path(__file__).resolve().parents[2]
        tasks_pool_path = renxinos_root.parent / "todo" / "tasks" / "全局任务池.md"

    if not tasks_pool_path.exists():
        return (
            f"错误：任务池文件不存在（{tasks_pool_path}）。"
            f"请检查 TODO_DIR 环境变量或目录结构。"
        )

    raw = tasks_pool_path.read_text(encoding="utf-8")

    # --- 解析「📍 一眼行动」节 ---
    # 结构：表格，每行格式为 | **标签** | 内容 |
    overview: dict[str, str] = {}
    overview_match = re.search(
        r"## 📍 一眼行动\s*\n(.*?)(?=\n## |\n---\n## )",
        raw, re.DOTALL
    )
    if overview_match:
        overview_section = overview_match.group(1)
        # 匹配表格行：| **key**（可选后缀）| value |
        for line in overview_section.split("\n"):
            # 提取第一列中的加粗文本作为 key（忽略括号后缀如「主块**（13:30–17:30）」）
            kv_match = re.match(
                r"\|\s*\*{0,2}([^*|\n]+?)\*{0,2}(?:（[^）]*）)?\s*\|\s*(.+?)\s*\|",
                line
            )
            if kv_match:
                key = kv_match.group(1).strip()
                value = kv_match.group(2).strip()
                if key and value and not key.startswith("-"):
                    overview[key] = value

    # --- 解析「☀️ 今日执行」节 ---
    # 提取日期、本周摘要、Day Planner 中未完成的 checkbox
    today_section_match = re.search(
        r"## ☀️ 今日执行\s*\n(.*?)(?=\n## |\n---\n## |$)",
        raw, re.DOTALL
    )
    today_date = ""
    week_summary = ""
    pending_tasks: list[str] = []
    if today_section_match:
        today_section = today_section_match.group(1)
        # 提取日期
        date_match = re.search(r"`(\d{4}-\d{2}-\d{2})`", today_section)
        if date_match:
            today_date = date_match.group(1)
        # 提取本周摘要
        week_match = re.search(r"\*\*本周\*\*[：:]\s*(.+?)(?:\n|$)", today_section)
        if week_match:
            week_summary = week_match.group(1).strip()
        # 提取未完成的任务（- [ ] 开头的行），过滤习惯打卡和备选区域
        in_skip_section = False
        for line in today_section.split("\n"):
            stripped = line.strip()
            # 检测需要跳过的区域
            if stripped.startswith("### 习惯打卡") or stripped.startswith("### 备选任务"):
                in_skip_section = True
                continue
            if stripped.startswith("### ") and in_skip_section:
                in_skip_section = False
            if in_skip_section:
                continue
            if stripped.startswith("- [ ]"):
                task = stripped[6:].strip()
                if task:
                    pending_tasks.append(task)

    # --- 拼接结果 ---
    parts: list[str] = []
    parts.append(f"## 今日任务概览（{today_date or '未知日期'}）")
    parts.append("")

    if week_summary:
        parts.append(f"**本周**：{week_summary}")
        parts.append("")

    # 一眼行动关键字段
    key_fields = ["主块", "副块", "最急 deadline"]
    for key in key_fields:
        if key in overview:
            parts.append(f"- **{key}**：{overview[key]}")

    if pending_tasks:
        parts.append("")
        parts.append("### 待完成任务（Day Planner 未勾选）")
        for task in pending_tasks:
            parts.append(f"- [ ] {task}")

    return "\n".join(parts)


def create_default_registry() -> ToolRegistry:
    """
    创建包含默认（mock）工具的注册表。

    S3 会用 create_registry_with_retriever() 替代此函数，
    把 search_notes 接上 V2 的真实检索。

    类比 Java：类似用默认配置创建 ApplicationContext
    """
    registry = ToolRegistry()

    registry.register(ToolDef(
        name="search_notes",
        description="在个人笔记库中检索与问题相关的 Markdown 片段。当你需要查找笔记、原则、规范中的内容时使用此工具。",
        parameters=[
            ToolParamDef(
                name="query",
                type="string",
                description="检索查询词，可以是关键词、问题或主题",
                required=True,
            ),
        ],
        fn=_mock_search_notes,
    ))

    registry.register(ToolDef(
        name="search_tasks",
        description="在个人任务池中检索今日任务与关键 deadline。当你需要查看今天要做什么、有哪些待办事项时使用此工具。",
        parameters=[
            ToolParamDef(
                name="query",
                type="string",
                description="任务检索查询词，如'今天主块'、'deadline'、'紧急任务'",
                required=True,
            ),
        ],
        fn=_mock_search_tasks,
    ))

    return registry


def create_registry_with_retriever() -> ToolRegistry:
    """
    创建包含真实检索工具的注册表（S3 使用）。

    search_notes → 调用 V2 的 retrieve_hybrid()（keyword 优先 + embedding 兜底）
    search_tasks → 暂仍为 mock（S4 替换）

    类比 Java：类似用生产环境的 DataSource 替换测试环境的 H2 内存库
    """
    registry = ToolRegistry()

    # --- search_notes：真实检索 ---
    # 延迟 import agent.py，避免循环依赖和冷启动时的 jieba 加载
    from src.agent import retrieve_hybrid

    def _real_search_notes(query: str) -> str:
        """
        真实的笔记检索工具。

        复用 V2 的 retrieve_hybrid()：
        1. 先跑 keyword 检索（本地 jieba 分词，零 API 成本）
        2. keyword 不足时调用 embedding 语义检索兜底
        3. 两路结果通过 RRF 融合

        类比 Java：类似调用已上线的数据查询服务，而非 mock 数据
        """
        hits = retrieve_hybrid(query, top_k=5)

        if not hits:
            return f"未检索到与「{query}」相关的笔记。"

        # 格式化检索结果为文本，供 LLM 阅读
        parts: list[str] = []
        for i, hit in enumerate(hits, start=1):
            file_name = hit.get("file", "")
            heading = hit.get("heading", "")
            content = hit.get("content", "").strip()
            score = hit.get("score", 0)

            # 截断过长内容，避免 Observation 膨胀
            if len(content) > 300:
                content = content[:300] + "…"

            parts.append(
                f"{i}. [{file_name} / {heading}] (score={score})\n"
                f"   {content}"
            )

        return "\n\n".join(parts)

    registry.register(ToolDef(
        name="search_notes",
        description="在个人笔记库中检索与问题相关的 Markdown 片段。当你需要查找笔记、原则、规范中的内容时使用此工具。",
        parameters=[
            ToolParamDef(
                name="query",
                type="string",
                description="检索查询词，可以是关键词、问题或主题",
                required=True,
            ),
        ],
        fn=_real_search_notes,
    ))

    # --- search_tasks：真实任务池（S4 替换）---
    # 优先使用真实实现，fallback 到 mock
    try:
        _real_search_tasks("")  # 预热检查，确认文件可读
        _search_tasks_fn = _real_search_tasks
    except Exception:
        _search_tasks_fn = _mock_search_tasks

    registry.register(ToolDef(
        name="search_tasks",
        description="在个人任务池中检索今日任务与关键 deadline。当你需要查看今天要做什么、有哪些待办事项时使用此工具。",
        parameters=[
            ToolParamDef(
                name="query",
                type="string",
                description="任务检索查询词，如'今天主块'、'deadline'、'紧急任务'",
                required=True,
            ),
        ],
        fn=_search_tasks_fn,
    ))

    return registry
