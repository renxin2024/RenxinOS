# ReAct 论文精读 —— ReAct: Synergizing Reasoning and Acting in Language Models

> 论文：Yao et al., 2023, "ReAct: Synergizing Reasoning and Acting in Language Models"
> 关联：`docs/learning/v3-raw-react-agent.md`、`src/agent_raw/react_loop.py`

## 1. 论文解决了什么问题

### 1.1 两种现有范式的各自缺陷

在 ReAct 之前，让 LLM 解决复杂任务有两种路：

| 范式 | 代表 | 核心 | 致命缺陷 |
|---|---|---|---|
| **Reasoning-only** | Chain-of-Thought (CoT) | 模型在脑子里一步步推理 | 推理基于"静态知识"，不知道外部世界的真实状态；会幻觉 |
| **Acting-only** | Recurrent Act-Only | 模型只输出 Action，不显式推理 | 没有思考过程，遇到复杂问题容易走偏；不可解释 |

CoT 的问题举例：模型说"根据笔记，GTD checkbox 应该写在任务池里"——但这句话是它在自己脑子里编的，根本没查过笔记。

Act-only 的问题举例：模型连续调了 5 次 search_notes，每次都换一个 query，但始终找不到答案——因为它没有停下来思考"我是不是在找错方向？"

### 1.2 ReAct 的核心命题

**把 Reasoning 和 Acting 交替进行，让两者互相增强。**

- Reasoning 帮助模型决定下一步该做什么（"我需要查笔记"）
- Acting 给模型提供外部世界的真实信息（"这是笔记里查到的内容"）
- 两者交替，形成闭环

类比 Java：CoT 像一个静态分析方法（看代码推理行为），Act-only 像盲跑测试（只有 pass/fail 没有日志）。ReAct 像带着断点调试——每执行一步，停下来看看变量的真实值，再决定下一步。

## 2. 方法设计

### 2.1 ReAct 循环的形式化定义

```
输入：用户问题 + 可用工具列表
输出：最终答案

while not finished:
    Thought: 思考下一步该做什么
    Action: 执行一个工具
    Observation: 拿到工具返回的真实结果
    → 把 Thought/Action/Observation 追加到上下文
    → 下一轮 LLM 看到完整的上下文来决策
```

### 2.2 为什么 Thought 不是多余的

一个自然的疑问：既然模型已经有 Action 了（"我要 search_notes"），为什么还需要显式的 Thought？

论文的回答：**Thought 是 Reasoning 的载体**。没有 Thought：
- Action 的选择没有解释——你不知道它为什么选这个工具
- 出错了无法回溯——你只能看到一连串失败的 Action
- 长序列中容易丢失意图——做了 5 步之后忘了最初要干嘛

Thought 有几种类型：
- 分析型："问题问的是 GTD checkbox 的位置，我需要查任务池相关笔记"
- 反思型："前两步没找到，可能是因为我搜的关键词不对，换个说法试试"
- 决策型："两个工具的结果都拿到了，我现在可以回答"
- 终止型："答案在笔记里确认了，给出最终答案"

### 2.3 和 Chain-of-Thought 的关系

两者都包含推理过程，但区别关键：

| | Chain-of-Thought | ReAct |
|---|---|---|
| 推理基础 | 模型静态知识 | 外部工具的真实返回 |
| 能否纠错 | 不能——模型以为对了就是对了 | 能——Observation 揭示了真相 |
| 信息来源 | 单一（模型参数） | 多元（外部 API） |
| 幻觉风险 | 高 | 低（Observation 是真实的） |

## 3. 关键实验发现

### 3.1 ReAct 不同时优于 CoT（这是论文的诚实之处）

论文发现了一个重要 nuance：

| 任务类型 | CoT | ReAct | 原因 |
|---|---|---|---|
| 知识密集型（QA、事实查询）| 差 | **好** | 外部检索补充了模型不知道的事实 |
| 推理密集型（数学、逻辑）| **好** | 差 | 工具返回的信息对纯推理没有帮助，反而增加推理噪音 |

这说明 **ReAct 不是万能药**——它最适合的是需要和外部世界交互的任务。这和你的项目场景（知识库 RAG → Agent 工具链）完全吻合。

### 3.2 消融实验的关键结论

论文通过移除不同组件来测各自贡献：

| 移除了什么 | 效果变化 | 结论 |
|---|---|---|
| Thought | 性能大幅下降 | Thought 不只是装饰，是真正的 Reasoning |
| Observation | 性能大幅下降，幻觉剧增 | 没有真实反馈，模型在自己骗自己 |
| 多个 Action 步骤 | 单步够用时多步没帮助 | ReAct 的步数和任务复杂度正相关 |

### 3.3 和你的 V3 代码的精确对应

| 论文概念 | V3 代码位置 | 对应关系 |
|---|---|---|
| Thought | `react_loop.py:218` — `parsed.thought` | 模型生成的思考文本 |
| Action | `react_loop.py:219` — `parsed.action` + `parsed.action_input` | 工具名 + 参数 |
| Observation | `react_loop.py:257-269` — `registry.execute()` | 工具的真实返回 |
| 循环终止 | `react_loop.py:238` — `parsed.final_answer` | 模型自主决定停止 |
| 上下文 | `react_loop.py:278-283` — `scratchpad` | Thought/Action/Observation 追加 |

## 4. 论文的局限和后续工作

论文本身只覆盖了 Wiki 和 QA 场景。后续工作扩展到了：

- **代码 Agent**：ReAct + 代码执行环境（如 OpenHands 的做法）
- **多 Agent**：多个 ReAct Agent 协作
- **Planning**：Plan-and-Execute 在 ReAct 前加了一个"先做计划"的阶段

## 5. 面试讲法

**30 秒版**：ReAct 论文证明了 Reasoning 和 Acting 交替进行比单独做推理（CoT）或单独执行（Act-only）效果更好。关键发现是 Observation 必须来自真实工具执行，否则模型会自己在脑子里编造。

**追问深度**：
- ReAct 不能取代 CoT → 推理密集型任务 CoT 更好，信息检索型 ReAct 更好
- 消融实验结论 → 移除 Thought 或 Observation 都会导致性能大幅下降
- 映射到你的项目 → V3 scratchpad 记录的就是 Thought/Action/Observation 序列，这是 ReAct 论文的核心闭环
