# MCP 协议规范阅读笔记 —— Model Context Protocol

> 规范来源：modelcontextprotocol.io 官方 spec
> 关联：`docs/learning/v3-raw-react-agent.md`（V3 手写 tools → V4 MCP 协议化）、`src/agent_raw/tools.py`（手写 ToolRegistry → MCP 的对照）

## 1. MCP 解决什么问题

### 1.1 MCP 之前的问题

每接入一个新工具（数据库、文件系统、API），你需要：读工具文档 → 写适配代码 → 定义 schema → 注册到 Agent。5 个工具 = 5 次重复劳动。

更严重的问题是：**你的 Agent 和工具强耦合**。换一个 Agent 框架（从 V3 手写到 V4 LangGraph）需要重写所有工具适配代码。

### 1.2 MCP 的核心思想

MCP 做的是一件事：**把工具提供者和工具消费者用标准协议解耦**。

| 角色 | MCP 术语 | 你的 V3 对应 |
|---|---|---|
| 工具提供者 | MCP Server | `ToolDef` + `ToolRegistry` |
| 工具消费者 | MCP Client（你的 Agent）| `run_react()` |
| 通信协议 | JSON-RPC 2.0 | 无——直接 Python 函数调用 |

类比 Java：MCP 相当于 JDBC。JDBC 之前每个数据库有自己的一套连接方式，JDBC 之后所有数据库遵循同一套接口。MCP Server = JDBC Driver，MCP Client = JDBC Connection，工具 = 数据库。

## 2. 协议核心：三个原语

MCP Server 暴露给 Client 的核心能力只有三种：

### 2.1 Tools

**tools/list**——Server 告诉 Client 我有哪些工具：

```json
// Client → Server
{"jsonrpc": "2.0", "method": "tools/list", "id": 1}

// Server → Client
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "search_notes",
        "description": "搜索个人 Obsidian 笔记",
        "inputSchema": {
          "type": "object",
          "properties": {
            "query": {"type": "string", "description": "搜索关键词"}
          },
          "required": ["query"]
        }
      }
    ]
  }
}
```

对比你 V3 的 `ToolDef.schema_dict()`——结构几乎一模一样。你在 V3 已经无意识地实现了 MCP 的 tool schema 格式。

**tools/call**——Client 让 Server 执行工具：

```json
// Client → Server
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "search_notes",
    "arguments": {"query": "GTD checkbox"}
  },
  "id": 2
}

// Server → Client
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {"type": "text", "text": "[8 个匹配结果...]"}
    ]
  }
}
```

对比你 V3 的 `registry.execute("search_notes", query="GTD checkbox")`——语义完全对应，只是 MCP 用 JSON-RPC 替代了函数调用。

### 2.2 Resources

**资源** = MCP Server 暴露的"可读数据"——文件、数据库记录、API 响应。

和 Tools 的区别：Tools 是"做事"，Resources 是"读东西"。类比 Java——Tools 是 POST/PUT（有副作用），Resources 是 GET（只读）。

### 2.3 Prompts

**Prompts** = MCP Server 提供的"预制 prompt 模板"。Server 可以定义"这是搜索笔记的最佳 prompt 模板"，Client 直接复用。

为什么需要这个？因为每个工具的"最佳提问方式"需要领域知识。`search_notes` 的 prompt 怎么写效果最好，只有写这个 tool 的人知道。Prompt 原语就是把这种知识也标准化传输。

## 3. Transport 层：STDIO vs HTTP

MCP 定义了两种通信方式：

| Transport | 机制 | 适用场景 |
|---|---|---|
| **STDIO** | stdin/stdout 传 JSON-RPC | 本地进程通信（最常用） |
| **HTTP + SSE** | HTTP POST + Server-Sent Events | 远程服务通信 |

**STDIO 的关键约束**：Server 的所有输出必须走 stdout 作为 JSON-RPC 消息。如果 Server 往 stdout 打了 debug 日志（如 `print("debug...")`），就会破坏 JSON-RPC 消息流，Client 解析失败。

这就是为什么你在做 MCP server 时，所有日志必须走 stderr——`sys.stderr.write()` 而不是 `print()`。

类比 Java：STDIO 就像 Socket 连接，stdout = output stream，你不能随使往 output stream 里塞非协议数据。

## 4. 和你 V3→V4 的精确映射

| V3 手写 | MCP | 变化 |
|---|---|---|
| `ToolDef` dataclass | `tools/list` 返回的 tool schema | 硬编码 → 协议发现 |
| `ToolRegistry` dict | MCP Server 的工具管理 | 本地字典 → 独立进程 |
| `registry.execute()` | `tools/call` JSON-RPC | 函数调用 → 网络/进程间调用 |
| `registry.schemas_list()` | `tools/list` | Python list → JSON-RPC response |
| `create_default_registry()` | MCP Server 启动注册 | 代码硬编码 → 独立部署 |
| `parse_tool_call()` | 模型原生 tool call | 正则解析 → model 内置（和 MCP 无关） |

**关键认知**：MCP 解决的是"工具定义和执行的标准化协议"问题，不解决"模型怎么调用工具"的问题。后者是 tool calling API 的事。

## 5. MCP 的设计意图——三点

1. **解耦工具和 Agent**：Agent 不绑定任何特定工具，通过 `tools/list` 动态发现
2. **工具可组合**：多个 MCP Server 各自提供不同能力，Agent 按需调用
3. **降低接入成本**：新工具只需实现 MCP Server 接口，不需要改 Agent 代码

## 6. V4 实现 MCP 的最小路径

你 V4 只需要做：

1. **MCP Server**：把 V3 的 `search_notes` 和 `search_tasks` 注册为 MCP tool，跑 STDIO 模式
2. **MCP Client**：LangGraph Agent 通过 MCP Client 连接到 Server，`tools/list` 发现工具，`tools/call` 执行工具
3. **验证**：用 MCP Inspector 或一个独立的测试脚本，确认 `tools/list` 返回正确、`tools/call` 返回笔记内容

不需要做 Resources 和 Prompts 原语——它们对 RenxinOS 当前场景不是必需的。

## 7. 面试讲法

**30 秒版**：MCP 是把工具接入 Agent 的标准化协议。它定义了三个原语——Tools（做事）、Resources（读东西）、Prompts（预制模板），用 JSON-RPC 通信。你的 V3 手写了 ToolRegistry，V4 用 MCP 把这个变成了标准化的独立服务。

**追问深度**：
- MCP vs OpenAPI → MCP 是为 AI Agent 设计的，OpenAPI 是为人类开发者设计的
- STDIO vs HTTP transport → 本地用 STDIO（性能好），远程用 HTTP+SSE
- 为什么 MCP 不能替代 tool calling API → MCP 解决工具从哪来，tool calling API 解决模型怎么调用工具——不同层次
