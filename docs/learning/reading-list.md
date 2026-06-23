> **关联**：[[Agent开发学习计划]] · [[RenxinOS-执行规格]] · **用途**：V2–V5 各阶段对照精读

---

## Agent / LLM 核心（5 篇）

| #   | 论文                                                                                           | 年份   | 对齐版本   | 为什么读                                                                  |
| --- | -------------------------------------------------------------------------------------------- | ---- | ------ | --------------------------------------------------------------------- |
| 1   | **ReAct: Synergizing Reasoning and Acting in Language Models** · Yao et al.                  | 2022 | **V3** | ReAct loop 源头。Thought→Action→Observation 循环设计，V3 手写对照。                |
| 2   | **Chain-of-Thought Prompting Elicits Reasoning in Large Language Models** · Wei et al.       | 2022 | **V3** | Agent reasoning 地基。不理解 CoT 就不会写 ReAct 的 prompt 模板。                    |
| 3   | **Toolformer: Language Models Can Teach Themselves to Use Tools** · Schick et al.            | 2023 | **V3** | 工具调用原理。手写 function calling 时理解 tool schema 设计。                        |
| 4   | **SWE-Agent: Agent-Computer Interfaces Enable Automated Software Engineering** · Yang et al. | 2024 | **V5** | 编码 Agent 经典。Agent-Computer Interface 设计、工具调用、沙箱执行，与 OpenHands 架构研究呼应。 |
| 5   | **Reflexion: Language Agents with Verbal Reinforcement Learning** · Shinn et al.             | 2023 | **V5** | Agent 自我反思改进循环。V5 质量门控+重试机制灵感来源。                                      |

---

## RAG / 检索增强（5 篇）

| #   | 论文                                                                                                           | 年份   | 对齐版本      | 为什么读                                                   |
| --- | ------------------------------------------------------------------------------------------------------------ | ---- | --------- | ------------------------------------------------------ |
| 6   | **Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks** · Lewis et al.                          | 2020 | **V1-V2** | RAG 开山之作。理解 V1 keyword RAG 的设计背景。                      |
| 7   | **Dense Passage Retrieval for Open-Domain Question Answering** · Karpukhin et al.                            | 2020 | **V2**    | DPR 双塔架构+in-batch negatives。V2 S3-S4 Embedding 接入直接对照。 |
| 8   | **BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models** · Thakur et al. | 2021 | **V2**    | 检索评测标杆。V2 10 题评测集+Recall@k 方法论参考。                      |
| 9   | **Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection** · Asai et al.             | 2023 | **V5**    | RAG+自我反思。检索→判断质量→决定是否检索更多→生成。V5 门控+路由参考。               |
| 10  | **Lost in the Middle: How Language Models Use Long Contexts** · Liu et al.                                   | 2023 | **V5**    | LLM 对中间上下文注意力最弱。V5 reranking 排序策略参考。                   |

---

## 阅读节奏

| 阶段 | 读哪些 | 目的 |
|---|---|---|
| V2 | #6 + #7 + #8 | 打 RAG 检索评测基础 |
| V3 | #1 + #2 + #3 | 手写 Agent 时对照原理 |
| V5 | #4 + #5 + #9 + #10 | 编码Agent架构+质量门控+reranking 收尾 |
