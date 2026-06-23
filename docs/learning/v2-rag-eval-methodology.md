> **创建**：2026-06-21 · **来源**：V2 S1 评测集设计实践 + 权威文献调研
> **关联**：[[RenxinOS-执行规格]] · `~/ai_brain/RenxinOS/data/eval_questions.json`
> **参考**：[Qdrant RAG Evaluation Guide](https://qdrant.tech/blog/rag-evaluation-guide/) · [Evidently AI RAG Evaluation](https://www.evidentlyai.com/llm-guide/rag-evaluation) · [arXiv 2405.07437 RAG Evaluation Survey](https://arxiv.org/html/2405.07437v2)

---

## RAG 评测题设计方法论

### 核心原则

评测题的目标是**量化检索质量**，而非测试 LLM 生成能力。每道题衡量的是：给定问题，检索系统能否召回正确的知识片段。

> **权威共识（Qdrant / Evidently / arXiv Survey）**：检索和生成**必须分开评**。出问题时需区分「没检索到」还是「检索到了但 LLM 瞎编」。
> - 检索侧：Recall@k / Precision@k / NDCG@k（评检索质量）
> - 生成侧：Faithfulness / Correctness / Answer Relevance（评答案质量，需 ground_truth_answer）

### 三层难度模型

| 类型 | 特征 | 考察能力 | 占比建议 |
|---|---|---|---|
| **单跳（single_hop）** | 问题关键词直接命中某个 chunk | 基础检索准确性 | 30% |
| **多跳（multi_hop）** | 需跨文件/跨 chunk 组合信息 | 多源召回完整性 | 25% |
| **模糊（fuzzy）** | 用户表述与笔记用词不匹配 | 语义理解/泛化能力 | 25% |
| **负例/拒答（unanswerable）** | 知识库中不存在答案 | 系统是否胡说/正确拒答 | 10% |
| **鲁棒性（paraphrase）** | 同一问题换 2-3 种表述 | 结果一致性 | 10% |

> **来源**：Evidently 强调 Stress Testing（边缘用例）和 Robustness Testing（同义改写一致性）是生产级评测的必备项。

### 设计步骤

**Step 1：盘点知识库覆盖域**

- 列出所有源文件及其主题
- 标注每个文件的 chunk 数量（密度高的区域多出题）
- 识别「跨文件关联」——同一概念在不同文件中出现的区域

**Step 2：按类型出题**

| 类型 | 出题策略 | 示例 |
|---|---|---|
| 单跳 | 从某个 chunk 的核心内容反向构造问题 | chunk 讲 4D → 问「什么是4D工作法？」 |
| 多跳 | 找跨 2+ 文件的共同主题，问需综合回答的问题 | 任务打勾规则散布在多处 → 问「打勾写在哪里？」 |
| 模糊 | 用口语化/间接表述替代笔记原文术语 | 笔记写「探索型无边界」→ 问「忍不住优化工具怎么办？」 |

**Step 3：为每题标注 ground truth**

每题必须包含：

```json
{
  "id": 1,
  "question": "问题文本",
  "type": "single_hop | multi_hop | fuzzy | unanswerable | paraphrase",
  "expected_source_files": ["应召回的文件名列表"],
  "expected_answer_keywords": ["答案中应出现的领域专属关键词"],
  "ground_truth_answer": "标准答案文本，用于后续 Faithfulness 评测",
  "difficulty": "easy | medium | hard",
  "note": "可选，设计意图或负例说明"
}
```

- `expected_source_files`：Recall@k 的分母——top-k 中应出现的文件（负例题为空数组）
- `expected_answer_keywords`：KW Score 的依据——用**领域专属词**，不用通用词
- `ground_truth_answer`：标准答案，用于后续 LLM-as-Judge / Faithfulness 评测
- 负例题的 `expected_answer_keywords` 用「未找到」「没有相关」「不包含」

**Step 4：验证题目质量**

- [ ] 单跳题：人肉搜索确认答案确实在目标文件中
- [ ] 多跳题：至少 2 个文件，每个文件都有相关内容
- [ ] 模糊题：问句中不出现目标文件的精确术语
- [ ] 关键词列表覆盖答案核心要点（3-6 个为宜）

### 评测指标

#### 当前使用（V2）

| 指标 | 计算方式 | 含义 |
|---|---|---|
| **Recall@k** | top-k 命中的期望文件数 / 期望文件总数 | 检索系统能否找到正确来源 |
| **KW Score** | top-k 内容中出现的期望关键词数 / 关键词总数 | 召回的内容是否包含答案要点 |

**基线建立**：先用当前检索方法跑全部题目，记录 Recall@k 和 KW Score，作为后续优化的对比基准。

#### 推荐扩展（V2 S5+ / V3）

| 指标 | 来源 | 含义 | 何时用 |
|---|---|---|---|
| **NDCG@k** | Qdrant, Evidently | 归一化折损累积增益——排在前面的相关文档权重更高 | 比较两种检索策略排序质量 |
| **MRR** | Qdrant | 平均倒数排名——第一个相关结果排第几 | 评估「首个命中」的速度 |
| **Hit Rate** | Evidently | top-k 中至少命中 1 个相关文档的比例 | 快速判断检索是否「能用」 |
| **Faithfulness** | Evidently, Ragas | 答案是否忠实于检索上下文，不编造 | 端到端评测 LLM 生成质量 |
| **Answer Correctness** | Qdrant, Ragas | 生成答案与 ground_truth 的语义相似度 | 端到端评测，需写 ground_truth_answer |
| **LLM-as-a-Judge** | Evidently, arXiv | 用 LLM 评判检索相关性和答案质量 | 大规模自动化评测 |

> **Evidently 最佳实践**：不要追求「一个完美指标」，而是根据观察到的失败模式选择高杠杆指标。调检索时用 Recall@k/NDCG；调生成时用 Faithfulness/Correctness；生产监控用 Answer Completeness + Topic Coverage。

### 常见陷阱

| 陷阱 | 表现 | 纠正 |
|---|---|---|
| 题目太简单 | 全是单跳、关键词直接匹配 | 加入模糊题，用口语化表述 |
| 关键词太宽泛 | 「任务」「方法」等通用词算命中 | 用领域专属词（如「铁律」「全局任务池」） |
| 期望文件不全 | 多跳题只标了 1 个文件 | 检查所有相关文件，标全 |
| 题目数量不足 | <10 题统计意义弱 | 至少 10 题，覆盖每个主要文件 |
| 只做 happy path | 没有负例/拒答题 | 加入知识库中不存在答案的题，测是否胡说 |
| 实验间重出题 | 每次跑评测换题目 | 固定测试集做 A/B 对比，新增题另存 |
| 只看总分 | 只看平均 Recall，不看分类差异 | 按 single_hop / multi_hop / fuzzy 分组看差异 |

### 合成数据生成（进阶）

> **来源**：Qdrant 推荐 4 种数据构建方式（手工 / LLM 合成 / Ragas / FiddleCube）；Evidently 强调「从 chunk 反向生成 QA 对」。

**反向生成流程**：
1. 取一个 chunk，让 LLM 生成「能被这个 chunk 回答的问题」
2. 同时生成基于该 chunk 的标准答案
3. 可指定用户人设（如「新手」「资深用户」）让问法更真实
4. 人工审核：删掉太简单/不自然的题

**适用时机**：知识库扩大后需快速补充评测题时，用合成数据 bootstrapping。

### RenxinOS 评测演进路线

| 阶段 | 内容 | 对应版本 |
|---|---|---|
| **V2 S1–S2** | 10 题手工 + Recall@k + KW Score | ✅ Recall@8=88.3% |
| **V2 当前** | 16 题诊断版 + pipeline 诊断 + 负例 + 同义改写 + ground_truth | ✅ Recall@8=61.5% · 3 种失败模式 |
| **V2 S3** | Embedding 语义检索接入，对比 keyword 基线 | 重点观察 paraphrase 一致性 |
| **V2 S5–S6** | NDCG@k / MRR；score 阈值拒答；检索与生成分离评测 | 自动回归测试 |
| **V3+** | LLM-as-a-Judge 自动评分；合成数据扩充；真实问题累积 | 持续迭代 |

### V1 基线（10 题，旧版）

- 出题：4 单跳 + 3 多跳 + 3 模糊 = 10 题
- Keyword 基线：Recall@8 = **88.3%** · KW Score = **91.5%**
- 薄弱点：模糊题 Recall 77.8%（Q8 仅 33.3%）

### V2 诊断版（16 题，当前）

> **优化动作**：补 ground_truth_answer（全题）· 加 2 道负例题 · 加 2 组同义改写 · 评测脚本加 pipeline 诊断（Barnett 失败模式）· KW Score 换领域专属词

- 出题：4 单跳 + 3 多跳 + 3 模糊 + 2 负例 + 4 改写 = **16 题**
- Keyword 基线：Recall@8 = **61.5%** · KW Score = **71.3%**（分数降但诊断价值大增）

**Failure Mode 分布**：

| 模式 | 数量 | 占比 | 含义 |
|---|---|---|---|
| NONE（正常） | 11 | 69% | 检索和内容都 OK |
| SEARCH_FAILURE | 3 | 19% | 有正确文档但没检索到 |
| SHOULD_REFUSE | 2 | 12% | 无内容但系统硬返回了结果 |

**3 个关键发现**：

1. **负例题暴露：系统不会拒答** — Q11/Q12 知识库无相关内容，但返回了 score=3.0 的无关结果。需设 score 阈值（如 < 5.0 时返回「未找到」）
2. **同义改写不一致** — 两组 paraphrase 全部 INCONSISTENT：含术语时 100%，完全口语化时 0%。keyword 检索对不含术语的口语化提问几乎失效
3. **Q9 检索偏差** — 「突然被打断」检索到 workflow 文档而非防护规则，「中断」在多处出现导致歧义

**待做**：
- V2 S3 Embedding 接入（解决口语化泛化问题）
- V2 S5 评测脚本加 score 阈值拒答逻辑
- V2 S5+ 引入 Faithfulness 评生成质量

---

## 企业级 RAG 评测实践（大规模数据量）

> 来源：[IBM arXiv:2410.12812](https://arxiv.org/abs/2410.12812)（企业 RAG 内容设计视角）· [Kapa.ai 100+ 团队经验](https://www.kapa.ai/blog/rag-best-practices)（Docker/CircleCI/Reddit/Monday.com）· [Evidently AI RAG 评测指南](https://www.evidentlyai.com/llm-guide/rag-evaluation)

### IBM 漏斗评测法

IBM 构建了专用评测 Web 应用，对每条用户提问做 **5 步漏斗标注**：

```
有效提问？ → 文档存在？ → 检索命中？ → 分类正确？ → 答案好？
    ↓             ↓            ↓            ↓           ↓
  过滤无效    补内容gap    修检索策略    修分类器    修prompt/内容
```

**核心思路**：不看总分，看**每步 drop-off**。实际案例：
- 7 月：40% 有效问题无对应文档 → 招 writer 补内容
- 12 月：文档覆盖提升到 75%，但检索下降 47% → 集中精力修检索
- 每次只聚焦漏斗中最大瓶颈

**大规模关键机制**：
- **Human-in-the-loop**：人工评测自然产生训练数据 → 反向训练自动评估器，逐步自动化
- **每周 30 分钟 review**：团队一起看结果、修内容、修检索
- **自动回归测试**：积累足够 question-topic-answer 三元组后，用 BLEU/ROUGE 做 batch 自动跑，人只看异常

### 大规模数据量策略

| 策略 | 做法 | 来源 |
|---|---|---|
| **分层抽样评测** | 按 query 类型分类（what-is / how-to / troubleshooting），每类抽样评测，不逐条全评 | IBM |
| **真实问题收集** | 内部 workshop + 论坛 + 早期用户 + 客服/售前支持，不用「猜」的问题 | IBM, Kapa.ai |
| **LLM-as-Judge 规模化** | 用 LLM 对每个 chunk 打 0-3 分相关性（微软报告 GPT-4 接近人类水平） | Evidently, Microsoft |
| **Delta 刷新评测** | 知识库更新时只测变化部分，不全量重跑 | Kapa.ai |
| **内容优化 for RAG** | 简化表格、加总结、解释图表、清除嵌套 | IBM |
| **自动回归测试** | 积累标注数据后，用 BLEU/ROUGE 做 batch 自动跑 | IBM |
| **用户反馈采集** | 1-click 三档（helpful / somewhat / unhelpful），但只有 <1% 用户会评 | Kapa.ai |

### 内容优化 > 调参（反直觉发现）

IBM 实验中发现：**改知识库内容本身比调检索策略、换 Embedding 模型更有效**。

- 案例：「CO2 工业前水平」问题，原文表述模糊导致检索失败，只改了几个字 → 准确率从失败变 100%
- 他们的 RAG 内容写作规范：简化表格、解释图表、加总结、清除嵌套、明确列表引导句
- 启示：**笔记写作方式本身就是优化杠杆**——写得越「问答友好」，检索效果越好

### 企业级 7 大失败模式（Barnett et al., 2024）

1. **Missing content** — 知识库里根本没有答案
2. **Search failure** — 有内容但检索没找到
3. **Context window limit** — 找到了但塞不进上下文
4. **Poor LLM answer** — 上下文对了但 LLM 回答差
5. **Wrong format** — 输出格式不对
6. **Vague answers** — 回答太笼统
7. **Incomplete answers** — 回答不完整

> 调试时按这 7 类逐一排查，比看一个总分有效得多。

### 对 RenxinOS 的启示

| 当前差距 | 企业做法 | 落地路径 |
|---|---|---|
| 只有 Recall + KW Score | 漏斗分析 + 7 类失败模式 | V2 S5: 评测脚本加 pipeline 诊断 |
| 10 题手工题 | 真实问题收集 + 合成数据 | 持续：记录自己实际提问，累积到评测集 |
| 无自动回归 | 固定测试集 + CI 跑分 | V2 S6: 每次改代码后自动跑评测集 |
| 未评生成质量 | Faithfulness + LLM-as-Judge | V2 S5+: 引入 ground_truth_answer 字段 |
| 笔记未做 RAG 优化 | 内容优化 for RAG | 随时：遇到检索失败先检查笔记写法 |
