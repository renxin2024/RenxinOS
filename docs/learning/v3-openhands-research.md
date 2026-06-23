> **用途**：V3 S0 调研笔记 — OpenHands 架构研究（代码理解/工具调用/沙箱执行）
> **创建**：2026-06-22 · **来源**：官方论文 + GitHub + 官方文档
> **关联**：[[RenxinOS-执行规格]] · [[Agent开发学习计划]]

---

# OpenHands 架构调研

## 0. 摘要

OpenHands 是 All-Hands-AI 开源的 AI 软件工程 Agent 平台，MIT 协议，64k+ GitHub Stars。
它经历了从 **V0（单体架构）** 到 **V1（模块化 SDK）** 的完整重构，是研究生产级 Agent 架构的优质参照。

本文档梳理其核心架构，重点关注：
1. **Agent Loop**（事件驱动执行循环）
2. **Tool System**（工具调用机制）
3. **Sandbox / Workspace**（沙箱执行环境）
4. 与 RenxinOS V3 手写 Agent 的参照关系

---

## 1. 架构演进：V0 → V1

### 1.1 V0：单体架构的问题

V0 是早期快速原型阶段的单体仓库，将 Agent 核心、评测套件、CLI/Web 前后端全部耦合在一起，引发了三大问题：

| 问题 | 描述 |
|---|---|
| **强制沙箱** | 所有工具调用必须跑在 Docker 容器内，本地运行需要打补丁绕过，导致代码重复 |
| **配置爆炸** | 140+ 字段、15 个类、2800 行配置代码，不同入口（CLI/Web/GitHub App）各自维护一套覆盖逻辑 |
| **边界模糊** | Agent 核心混入了评测 benchmark 依赖，部署重、版本冲突频繁 |

### 1.2 V1：四大设计原则

V1 基于四条原则完整重构：

| 原则 | 含义 |
|---|---|
| **沙箱可选（Optional Isolation）** | 默认本地运行，需要安全隔离时才套容器，对齐 MCP 协议假设 |
| **默认无状态（Stateless by Default）** | Agent、Tool、LLM 均为不可变 Pydantic 模型；唯一可变体是 `ConversationState` |
| **关注点分离（Separation of Concerns）** | SDK 核心与 CLI、Web UI、GitHub App 解耦；下游消费 SDK API，不复制逻辑 |
| **两层可组合（Two-layer Composability）** | 部署层（SDK/Tools/Workspace/Server 四包）+ 能力层（类型化组件扩展） |

---

## 2. V1 四包模块化设计

```
openhands.sdk          ← 核心抽象：Agent、Conversation、LLM、Tool、事件系统
openhands.tools        ← 具体工具实现（bash、文件读写、浏览器等）
openhands.workspace    ← 执行环境（本地/Docker/云 API）
openhands.agent_server ← REST/WebSocket 服务端，供远程执行
```

四包可按需组合：
- **本地快速原型**：只用 `sdk` + `tools`
- **本地沙箱**：加 `workspace`（DockerWorkspace）
- **远程生产**：加 `agent_server`，通过 HTTP/WS 控制

> 参考：[arxiv 2511.03690 §4.1](https://arxiv.org/html/2511.03690v1)

---

## 3. Agent Loop：事件驱动执行

### 3.1 核心模型：Event-Sourced State

V1 的状态管理采用**事件溯源（Event Sourcing）**模式——所有交互都是追加到日志的不可变事件。

```
用户消息
    ↓
Agent 生成 ActionEvent（工具调用 + 思考链）
    ↓
SecurityAnalyzer 评估风险等级
    ↓
（高风险 → 暂停等用户确认）
    ↓
ToolExecutor 执行工具
    ↓
ObservationEvent（执行结果）
    ↓
写回 ConversationState.event_log
    ↓
下一轮 LLM 调用（携带更新后的历史）
    ↓
（repeat 直到 finish_reason = stop 或 max_steps）
```

### 3.2 事件层级

| 父类 | 子类及用途 |
|---|---|
| `LLMConvertibleEvent` | `MessageEvent`（用户/助手消息）、`ActionEvent`（工具调用）、`SystemPromptEvent` |
| `ObservationBaseEvent` | `ObservationEvent`（工具成功结果）、`UserRejectObservation`、`AgentErrorEvent` |
| `Event`（内部，不传给 LLM） | `ConversationStateUpdateEvent`、`CondensationRequest`、`PauseEvent` |

> 参考：[arxiv 2511.03690 §4.2，Table 1](https://arxiv.org/html/2511.03690v1)

### 3.3 ConversationState：唯一状态源

```python
# 伪代码示意（来自论文 §4.2）
class ConversationState:
    agent_status: AgentExecutionStatus  # RUNNING / PAUSED / FINISHED / ERROR
    stats: ConversationStats
    confirmation_policy: ConfirmationPolicy
    event_log: EventLog  # 追加写，不可删改
```

- Agent、Tool、LLM 全部不可变（Pydantic 模型，构造时验证）
- 只有 `ConversationState` 可变，持久化到 `base_state.json` + 每条事件单独 JSON
- 断点续跑：加载 `base_state.json` + 重放事件日志

### 3.4 Agent 的执行接口

Agent 是**无状态的事件处理器**，通过回调发射事件：

```python
# 简化版
class Agent:
    llm: LLM         # 不可变
    tools: list[Tool]  # 不可变

    def step(self, state: ConversationState) -> None:
        # 不直接返回结果，通过 on_event 回调发射
        events = self._call_llm(state.event_log)
        for event in events:
            self.on_event(event)  # 安全检查 → 工具执行 → 写状态
```

这个设计支持：
- **暂停/恢复**（PauseEvent + resume()）
- **实时流式输出**（中间步骤通过 WebSocket 推送）
- **安全拦截**（on_event 链路中插入 SecurityAnalyzer）

> 参考：[arxiv 2511.03690 §4.5](https://arxiv.org/html/2511.03690v1)

---

## 4. Tool System：Action-Execution-Observation

### 4.1 三元组模式

每个工具由三部分组成：

```
LLM 生成 JSON tool call
        ↓
   [Action]  ← Pydantic 输入模型，校验 schema
        ↓
[ToolExecutor]  ← 实际执行逻辑（bash、文件 I/O 等）
        ↓
 [Observation]  ← 结构化输出，含 to_llm_content() 转给 LLM
```

```python
# 来自论文 Figure 4（简化）
class Action(Schema):
    def visualize(self) -> str: ...   # UI 展示

class Observation(Schema):
    def to_llm_content(self) -> str: ...  # 给 LLM 看的文本

class ToolDefinition[ActionT, ObservationT]:
    action_type: type[Action]
    observation_type: type[Observation]
    executor: ToolExecutor
    def to_mcp_tool(self) -> dict: ...
    def to_openai_tool(self) -> dict: ...
```

### 4.2 MCP 集成

MCP 工具被当成一等工具对待：
- `MCPToolDefinition` 继承标准 `ToolDefinition`
- `MCPToolExecutor` 委托给 FastMCP 的 `MCPClient` 处理协议细节
- 外部 MCP 工具与内置工具行为完全一致（输入校验 + 类型安全 + LLM 序列化）

> 参考：[arxiv 2511.03690 §4.4](https://arxiv.org/html/2511.03690v1)

### 4.3 默认工具集（`openhands.tools`）

| 工具 | 功能 |
|---|---|
| Bash 终端（tmux） | 执行 shell 命令，支持交互式进程 |
| 文件读写 | 创建、编辑、读取代码文件 |
| 浏览器（Chromium） | 截图、点击、填表、爬取网页 |
| VSCode Web | 图形化代码查看与编辑 |
| VNC 桌面 | 完整 GUI 操作 |
| MCP 客户端 | 外部 MCP server 接入 |

---

## 5. Workspace / Sandbox：沙箱抽象

### 5.1 抽象层

```python
class BaseWorkspace(ABC):
    def execute_command(self, command: str) -> CommandOutput: ...
    def file_upload(self, path: str, content: bytes) -> None: ...
    def file_download(self, path: str) -> bytes: ...
```

两种实现：

| 实现 | 底层 | 适用场景 |
|---|---|---|
| `LocalWorkspace` | `subprocess.run()` 直接调用 | 本地快速迭代，无容器开销 |
| `RemoteWorkspace` | HTTP 调用远端 Agent Server | 生产沙箱、多租户隔离 |

工厂类 `Workspace(...)` 根据参数自动选择：

```python
# 只给 working_dir → LocalWorkspace
conv = Conversation(agent, workspace="/path/to/project")

# 给 Docker/host → RemoteWorkspace（两行改动，其余代码不变）
with DockerWorkspace(...) as ws:
    conv = Conversation(agent, workspace=ws)
```

> 参考：[arxiv 2511.03690 §4.10, Figure 5, 7](https://arxiv.org/html/2511.03690v1)

### 5.2 容器化生产部署

每个 Agent 实例独立容器，内置：
- Agent Server（REST/WebSocket）
- VSCode Web
- VNC 桌面
- Chromium 浏览器

容器通过 WebSocket 将执行事件实时流回 UI，无需轮询。

---

## 6. 安全机制

### 6.1 SecurityAnalyzer + ConfirmationPolicy

```
工具调用请求
    ↓
SecurityAnalyzer.analyze(action) → 风险等级 {LOW / MEDIUM / HIGH / UNKNOWN}
    ↓
ConfirmationPolicy.should_confirm(risk) → 是否暂停等用户确认
    ↓
用户确认 → 恢复执行 / 拒绝 → Agent 重试
```

内置实现：
- `LLMSecurityAnalyzer`：LLM 在生成工具调用时同步附加 `security_risk` 字段
- `ConfirmRisky` 策略：超过阈值（默认 HIGH）自动暂停

> 参考：[arxiv 2511.03690 §4.9](https://arxiv.org/html/2511.03690v1)

---

## 7. LLM 抽象层

| 特性 | 说明 |
|---|---|
| 统一接口 | 通过 LiteLLM 支持 100+ LLM provider |
| 多模型路由 | `RouterLLM`：按内容类型/成本选择模型，参见 Figure 3 |
| 非 function-calling 兼容 | `NonNativeToolCallingMixin`：prompt 模板模拟 function calling |
| 推理模型支持 | 原生捕获 ThinkingBlock（Anthropic）、ReasoningItemModel（OpenAI）|

> 参考：[arxiv 2511.03690 §4.3](https://arxiv.org/html/2511.03690v1)

---

## 8. Context Window 管理（Condenser）

长对话问题：历史事件不断增长，超出 LLM 上下文窗口。

解决方案：`Condenser` 系统

```
历史事件达到阈值
    ↓
CondensationRequest 触发
    ↓
LLMSummarizingCondenser 生成摘要
    ↓
CondensationEvent 写入日志（替换被压缩的旧事件）
    ↓
发给 LLM 时：删去被压缩事件 + 插入摘要
    ↓
原始完整日志保持不变（用于 debug 和 replay）
```

效果：成本降低 2x，性能无明显损失。

> 参考：[arxiv 2511.03690 §4.6](https://arxiv.org/html/2511.03690v1) · [All-Hands AI Blog](https://openhands.dev/blog/openhands-context-condensensation-for-more-efficient-ai-agents)

---

## 9. 与 RenxinOS V3 的参照关系

RenxinOS V3 是**手写 ReAct Agent**，目标是「理解轮子怎么转」。对照 OpenHands：

| OpenHands 组件 | V3 手写对应 | 说明 |
|---|---|---|
| `Agent.step()` + `on_event()` 回调 | `while loop` + `if/else` 分支 | V3 用 Python 控制流手写，OH 用事件回调分离 |
| `ActionEvent` + `ObservationBaseEvent` | tool_call 解析 + 结果字符串 | V3 用 dict，OH 用 Pydantic typed 模型 |
| `ConversationState.event_log` | `state dict` + `messages list` | V3 手动维护 history，OH 用 append-only EventLog |
| `ToolDefinition[Action, Observation]` | 手写 tool schema + JSON 解析 | V3 直接写 JSON schema，OH 抽象三元组 |
| `LocalWorkspace` | 无沙箱，直接 subprocess | V3 暂无沙箱要求，到 V4 考虑 |
| `SecurityAnalyzer` | 无 | V3 不含安全机制，属于 V5 范围 |
| `Condenser` | 无 | V3 对话历史手动截断 |

**V3 重点借鉴**：
1. **事件结构**：把 tool_call 和 observation 结构化为类（而非裸 dict），有助于代码可读性
2. **状态单源**：所有可变状态集中在一个 `state` 对象，而非散落多个变量
3. **执行循环解耦**：`step()` 只负责生成事件，执行/持久化交给上层 — V3 可在 while 循环里模拟这个边界

---

## 10. 基准测试表现（参考）

| Benchmark | 模型 | 性能 |
|---|---|---|
| SWE-Bench Verified | Claude Sonnet 4.5 | 72.8% |
| SWE-Bench Verified | GPT-5 (reasoning=high) | 68.8% |
| GAIA val set | Claude Sonnet 4.5 | 67.9% |

> 参考：[arxiv 2511.03690 Table 2](https://arxiv.org/html/2511.03690v1)

---

## 参考资料

| # | 资料 | 类型 | 链接 |
|---|---|---|---|
| 1 | **OpenHands Software Agent SDK 论文**（arXiv 2511.03690） | 学术论文（2025 ICLR 相关） | https://arxiv.org/html/2511.03690v1 |
| 2 | **OpenHands: An Open Platform for AI Software Developers**（ICLR 2025） | 学术论文 | https://openreview.net/forum?id=OJd3ayDDoF |
| 3 | **OpenHands GitHub 主仓库** | 代码/README | https://github.com/All-Hands-AI/OpenHands |
| 4 | **OpenHands Software Agent SDK 代码仓** | 代码 | https://github.com/OpenHands/software-agent-sdk |
| 5 | **OpenHands 官方文档 · SDK 入口** | 官方文档 | https://docs.openhands.dev/sdk |
| 6 | **OpenHands 官方文档 · 简介** | 官方文档 | https://docs.openhands.dev/overview/introduction |
| 7 | **All-Hands AI Blog · Context Condensation** | 技术博客 | https://openhands.dev/blog/openhands-context-condensensation-for-more-efficient-ai-agents |

---

> **调研结论**：OpenHands V1 的核心思想是「事件溯源 + 无状态组件 + 可选沙箱」，这与 ReAct 原理（Reason → Act → Observe）完全对应，只是生产化程度更高。V3 手写 Agent 不需要照搬所有机制，但理解这三个核心概念足以写出结构清晰的 ReAct loop。
