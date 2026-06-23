# V3：手写 ReAct Agent — 知道 Agent 的轮子怎么转

> 代码路径：`src/agent_raw/react_loop.py`、`src/agent_raw/tools.py`、`src/agent_raw/react_trace_viewer.py`
> 验收清单：`~/ai_brain/todo/tasks/projects/Agent开发学习计划/RenxinOS-验收清单.md#V3（6/29）`
> 关联笔记：`docs/learning/v1-rag-keyword.md`、`docs/learning/v2-eval-embedding.md`

## 1. 为什么需要它

V1/V2 做的是 RAG：检索 → 拼 prompt → LLM 回答。但这是个"一次性"流程——模型不能说"我不确定，让我再查一下"，不能连续调用多个工具。

V3 要实现的是 Agent 的核心：**模型能自主决定什么时候查笔记、什么时候查任务池、什么时候停止并给最终答案**。这就是 ReAct（Reasoning + Acting）模式。

类比 Java：V1/V2 像一个 servlet——请求来了，执行一次，返回。V3 像一个状态机——可以在多个状态间跳转，根据上一步的结果决定下一步。

## 2. 第一性原理

### ReAct 的三要素

| 要素 | 含义 | 类比 |
|---|---|---|
| **Thought** | 模型思考当前应该做什么 | 类似 Java 方法的 Javadoc——解释意图 |
| **Action** | 模型决定调用哪个工具、传什么参数 | 类似 RPC 调用——指定服务名 + 参数 |
| **Observation** | 工具执行后返回的真实结果 | 类似 RPC 的返回值——模型只能基于这个推理 |

### 循环结构

```
while step <= max_steps:
  LLM(question + scratchpad) → Thought/Action 或 Final Answer
  if Final Answer → 终止
  if Action → 执行工具 → Observation → 追加到 scratchpad
```

关键设计：**Observation 必须来自工具真实执行，不允许模型自己编造**。`stop=["Observation:"]` 就是用来防止模型"幻想"工具返回结果的。

### Tool Schema 与 OpenAPI 的关系

在 V3 手写中，每个工具都有：
- `name`：工具名（类似 REST 的 endpoint）
- `description`：告诉模型何时调用
- `parameters`：参数 schema（类似 JSON Schema，来自 OpenAPI 规范）

这恰好对应 OpenAPI spec 中的 `paths.{endpoint}.get.parameters`——工具 schema 的设计灵感就是来自 REST API 文档标准。理解这一点后，V4 的 MCP 协议就容易懂了：MCP 本质是把 OpenAPI 的"描述 API 给人类看"换成了"描述工具给 AI Agent 看"。

## 3. 最小代码

| 组件 | 文件 | 核心逻辑 |
|---|---|---|
| ToolDef | `src/agent_raw/tools.py:52` | 工具的结构化定义（name + description + params + fn） |
| ToolRegistry | `src/agent_raw/tools.py:131` | 工具注册表（register / get / execute / schemas_list） |
| parse_tool_call | `src/agent_raw/tools.py:218` | 从 LLM 输出中解析工具调用（支持两种格式） |
| ReactLooper | `src/agent_raw/react_loop.py:160` | 主循环：prompt → LLM → 解析 → 执行 → observation → 循环 |
| ParseResult | `src/agent_raw/react_loop.py:77` | 解析结果（thought + action + final_answer 三选） |
| build_react_prompt | `src/agent_raw/react_loop.py:120` | 拼装 ReAct prompt（工具描述 + scratchpad + 问题） |

## 4. 运行轨迹

```
Q: "GTD 任务 checkbox 可以写在哪里？今天主块是什么？"

Step 1:
  Thought: 需要回答两个问题。先查第一个：checkbox 写在哪。
  Action: search_notes
  Action Input: GTD checkbox 写在哪
  Observation: [从 retrieve_hybrid 返回 8 个匹配 chunk，最高分 8 分]

Step 2:
  Thought: 第一个问题有答案了——任务池和 projects 目录。
           现在需要查第二个问题：今天主块是什么。
  Action: search_tasks
  Action Input: 今日主块
  Observation: 今日 13:30–17:30 主块：V3 S1 ReAct loop 骨架

Step 3:
  Thought: 两个问题都有答案了。给出最终回答。
  Final Answer: 1) GTD checkbox 只允许写在全局任务池的"今日执行"和 projects/ 下的项目文件。
                2) 今天主块是 V3 S1 手写 ReAct loop 骨架。
```

## 5. 与框架的对应关系

| 手写 V3 | LangGraph V4 | 变化 |
|---|---|---|
| `while max_steps:` | `StateGraph` + conditional edge | 显式循环 → 声明式图 |
| `scratchpad` 字符串 | `AgentState.messages` | 字符串拼接 → 结构化消息列表 |
| `parse_llm_output()` | model 原生 tool call | 正则解析 → model 内置能力 |
| `ToolRegistry.execute()` | `ToolNode` | 手动调度 → LangGraph 自动调度 |
| `stop=["Observation:"]` | 不再需要 | 框架层保证工具结果与文本不混 |
| `max_steps` 整型 | graph recursion limit | 手工限制 → 框架配置 |
| `_save_trace()` 写 JSONL | LangGraph tracing | 自定义 → 框架内置 tracing |

## 6. 面试讲法

**30 秒版**：V3 手写了完整的 ReAct Agent Loop——从 prompt 构造到 LLM 调用到工具解析再到 observation 回传的整个闭环，没有用任何框架。目的是理解 Agent 的底层机制再学框架。

**2 分钟版**：
1. 设计决策：先手写再框架。先用 while loop + 正则解析跑通 Agent，V4 再 LangGraph 重写，面试时能对比手写版和框架版的差异
2. 核心组件：ToolDef（工具 schema）+ ToolRegistry（工具注册和执行）+ parse_tool_call（LLM 输出解析）+ ReactLooper（主循环编排）
3. 关键设计：`stop=["Observation:"]` 防止模型编造工具返回；两种解析格式兼容（文本 ReAct + JSON tool_call）
4. 与框架的映射：while loop → StateGraph, scratchpad → State.messages, 正则解析 → model 原生 tool call
5. 反思：全局 state 不好扩展（V4 用 typed dict 改进），循环退出的条件判断需要更细粒度

## 7. 我踩过的坑

1. **模型会编造 Observation**——不设 `stop=["Observation:"]` 时，模型可能自己生成假的工具返回。这是文本 ReAct 的经典问题，V4 用 model 原生 tool call 彻底解决
2. **action_input 为空**——模型有时只输出 `Action: search_notes` 不带 input，解析时需处理空参数情况
3. **JSON tool_call 格式解析失败 → 回退到文本格式**——`parse_tool_call()` 先试 JSON，失败后回退到文本 ReAct 格式。这是容错设计，面试可以讲
4. **全局 `_current_trace` 在测试中被 mock 污染**——trace 是模块级变量，不是线程安全。V5 要改为 request-scoped tracing
5. **`sync def` 是同步的**——当前 loop 是同步的，一次只能服务一个请求。Python 中 `async def` 配合 `await` 才能让 FastAPI 并发处理多个请求，但 Agent loop 改成异步需要从 LLM 调用到工具执行全链路改造
