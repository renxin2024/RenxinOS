# 为什么有的模型有 tool calling API，有的没有？

> 问题来源：用户从"模型选型"的追问——tool calling API 到底区别在哪？
> 关联：`docs/learning/v3-why-llm-can-call-tools.md`、`src/agent_raw/tools.py`、`src/agent_raw/react_loop.py`

## 1. 核心答案（一句话）

区别不在模型的数学结构，在**后训练阶段有没有用工具调用序列做 fine-tune**，以及**推理层有没有提供结构化接口来注入工具定义和校验输出格式**。

没有 tool calling API = 你往 prompt 里手写工具描述 + 自己正则解析模型的文本输出。
有 tool calling API = API 层帮你注入工具定义 + 校验输出格式 + 返回结构化对象。

## 2. 无 tool calling API 的玩法 —— 就是你 V3 在做的事

### 2.1 工具描述注入——手写 prompt

```python
# react_loop.py:120 — build_react_prompt()
prompt = f"""
你可以使用以下工具：
{registry.format_all_for_prompt()}
 
用户问题：{question}
"""
```

模型看到这段 prompt 后，试图输出符合格式的文本。但没有人保证它一定会输出——它可能跳过工具直接回答，可能用错格式，可能在 JSON 里多打一个逗号。

### 2.2 工具调用解析——手写正则

```python
# tools.py:218 — parse_tool_call()
def parse_tool_call(text: str) -> ToolCall | None:
    # 先试 JSON 格式
    json_match = re.search(r"```(?:tool_call|json)\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if json_match:
        return ToolCall(...)
    # 回退到文本 ReAct 格式
    action_match = re.search(r"Action:\s*(.+?)\n", text)
    ...
```

模型输出的是一段文本。你要从文本中识别：这到底是一个工具调用，还是普通回答？如果是工具调用，工具名是什么？参数是什么？

**这些都不是模型替你做的——是你写的正则和 JSON 解析在替模型补位。**

## 3. 有 tool calling API 的玩法 —— V4 要迁移到的方向

### 3.1 工具描述注入——API 参数

```python
# V4 代码（伪代码示意）
response = client.chat.completions.create(
    model="xxx",
    messages=[{"role": "user", "content": "今天主块是什么？"}],
    tools=[  # ← 工具定义作为 API 参数传入
        {
            "type": "function",
            "function": {
                "name": "search_tasks",
                "description": "搜索今日任务",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"}
                    },
                    "required": ["query"]
                }
            }
        }
    ]
)
```

和 V3 的区别：工具描述不是拼进 prompt 里的文本，而是作为结构化参数传给 API。API 层负责把工具定义注入模型的上下文——你不需要知道是怎么注入的。

### 3.2 工具调用解析——SDK 返回结构化对象

```python
# V4 代码（伪代码示意）
choice = response.choices[0]
if choice.finish_reason == "tool_calls":
    for tool_call in choice.message.tool_calls:
        name = tool_call.function.name      # 直接拿到工具名
        args = json.loads(tool_call.function.arguments)  # 直接拿到已解析的参数
        # 执行工具...
else:
    answer = choice.message.content  # 普通文本回答
```

和 V3 的区别：不需要 `parse_tool_call()` 正则解析。SDK 直接把模型输出的结构化 tool_call 对象返回给你。字段名、参数类型都是校验过的。

## 4. 为什么模型能做到这一点？——后训练的关键差异

回顾训练三阶段笔记的结论：

| 阶段 | 普通模型 | 有 tool calling API 的模型 |
|---|---|---|
| 预训练 | 一样的——都学会了语言 | 一样的 |
| **后训练** | 训练数据是普通对话 | **训练数据含工具调用序列** |
| 推理层 | 纯文本接口 | **API 层注入 tools 定义 + 校验输出** |

关键在后训练这一步。训练数据的格式差异：

**普通模型的后训练数据**：
```
用户：什么是 GTD？
助手：GTD 是 Getting Things Done 的缩写...
```

**有 tool calling 模型的后训练数据**：
```
系统：你有工具 search_notes(query)，用来搜索笔记。
用户：GTD checkbox 写在哪？
助手：{"name": "search_notes", "arguments": {"query": "GTD checkbox"}}
工具返回：[8 个匹配结果...]
助手：根据笔记，GTD checkbox 只允许写在...
```

模型被反复训练「当需要查东西时 → 必须输出 JSON → 不能自己编 → 等工具返回值再回答」。这就是它比纯 prompt 约束「听话」的根本原因。

## 5. 和你 V3→V4 迁移的精确对应

| V3 手写版 | V4 有 tool calling API 版 | 什么变了 |
|---|---|---|
| `build_react_prompt()` 手写工具描述 | SDK `tools` 参数 | 注入方式：文本 → 结构化 |
| `parse_tool_call()` 正则解析 + JSON 解析 | `response.choices[0].message.tool_calls` | 解析方式：你写正则 → SDK 返回对象 |
| 格式不稳定的模型输出 | fine-tune 过的结构化输出 | 可靠性的来源：prompt 约束 → 训练数据 |
| `stop=["Observation:"]` 防编造 | 不再需要 | 模型被训练成不编造工具返回值 |

## 6. MCP 在其中的位置

MCP 解决的不是"模型怎么调用工具"的问题，而是"工具定义从哪来"的问题：

- 没有 MCP：工具定义写在你的代码里（V3 的 `create_default_registry()`）
- 有 MCP：工具定义由外部 MCP server 提供（`tools/list` → `tools/call`）

但无论工具定义从哪来，**模型能不能稳定输出 tool_call，取决于底层模型有没有后训练这一步**。MCP 只是工具定义的运输通道，不是模型能力的来源。

## 7. 面试讲法

**30 秒版**：区别不在模型数学结构，在后训练有没有用工具调用序列做 fine-tune，和推理层有没有提供结构化工具定义接口。V3 手写 prompt + 正则 = 无 API 做法，V4 tool_call API = 有 API 做法。

**2 分钟版**：
1. 无 API = prompt 手写工具描述 + 正则解析 LLM 输出文本（就是 V3 的代码）
2. 有 API = SDK `tools` 参数注入 + 后训练保证了格式稳定 + SDK 返回结构化对象
3. 核心差异在后训练数据：普通模型训练数据是对话，tool_call 模型的训练数据含工具调用序列
4. MCP 解决工具定义从哪来，tool_call API 解决模型能否稳定调用——两者互补但不重叠
5. 你的项目叙事：V3 体会了无 API 的痛（格式不稳定、需要 stop 序列、手动解析），V4 用有 API 的方式看框架解决了哪些问题
