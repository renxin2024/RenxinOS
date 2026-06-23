# V2：Embedding 检索与评测体系 — 从「能跑」到「能说清楚指标」

> 代码路径：`src/embedding.py`、`src/agent.py`（hybrid 分支）、`scripts/run_*.py`、`data/eval_questions.json`
> 验收清单：`~/ai_brain/todo/tasks/projects/Agent开发学习计划/RenxinOS-验收清单.md#V2（6/30）`

## 1. 为什么需要它

V1 的 keyword 检索有两个致命弱点：
- **口语化匹配失败**：问"打勾"搜不到"checkbox"，问"主块"搜不到"今日执行"
- **没有量化指标**：只知道"能跑"，不知道"多好"。投简历时面试官会问：你的检索准确率多少？

V2 要回答两个问题：检索质量能不能用数字说话？口语化问题怎么解决？

## 2. 第一性原理

### Embedding 的核心数学

- Embedding = 把文本映射为 1024 个浮点数（向量）
- 语义相近的文本，向量方向相近 → 余弦相似度高
- 类比 Java：`hashCode()` 只能判断相等/不等，Embedding 能判断相似程度

### 检索评测的核心循环

```
eval_questions.json → for each question:
  1. 用当前检索策略找 top_k 个 chunk
  2. 对比 expected_source_files（标注的正确答案）
  3. 计算 Recall@k = 召回文件数 / 应召回文件数
  4. 计算 KW Score = 命中关键词数 / 应命中关键词数
  5. 分类失败模式：SEARCH_FAILURE / SHOULD_REFUSE / CONTEXT_INCOMPLETE
```

## 3. 最小代码

| 模块 | 文件 | 核心逻辑 |
|---|---|---|
| Embedding API | `src/embedding.py:_get_embedding()` | DashScope text-embedding-v4 → 1024 维 |
| 余弦相似度 | `src/embedding.py:_cosine_similarity()` | `dot(a,b)/(norm(a)*norm(b))` |
| 混合检索 | `src/agent.py:retrieve_hybrid()` | keyword ≥ 4 条 → 直接用；不足 → embedding 兜底 + RRF |
| RRF 融合 | `src/agent.py:_rrf_merge()` | `score = 1/(k+rank)`，k=20 |
| 评测集 | `data/eval_questions.json` | 16 题 × 5 种题型 |
| 评测脚本 | `scripts/run_hybrid_eval.py` | Recall@k + KW + failure 分类 |
| 健全检查 | `scripts/eval_sanity_check.py` | 源文件存在性 + 关键词存在性 + ground truth 覆盖 |

## 4. 运行轨迹

```
Q: "GTD 任务的 checkbox 可以打勾在什么地方？"（口语化改写）

→ keyword 检索："checkbox" 命中但分数不够 (top-1 ≤ 6 分)
→ 判定：不满足 KW_RECALL_THRESHOLD，触发 embedding 兜底
→ embedding: text-embedding-v4 把问题转为向量 → 102 chunks 逐一算余弦
→ RRF: keyword 排名 + embedding 排名 → 1/(20+rank_kw) + 1/(20+rank_em)
→ per-file dedup: 同一文件最多取 2 个 chunk
→ prompt: 拼接 top-8 → LLM 回答

最终指标：Recall@8=84.4%，KW Score=82.5%，0 failure
```

## 5. 与框架的对应关系

| 手写 V2 | LangChain / 框架概念 |
|---|---|
| `_get_embedding()` | LangChain `OpenAIEmbeddings` |
| `_cosine_similarity()` | `numpy.dot()/linalg.norm()` (LangChain 内置) |
| `retrieve_hybrid()` | LangChain `EnsembleRetriever` |
| `_rrf_merge()` | LangChain `ReciprocalRankFusion` |
| `run_hybrid_eval.py` | LangSmith Evaluation / Ragas |
| 16 题评测集 json | `QAEvalDataset` |

## 6. 面试讲法

**30 秒版**：V2 在 keyword 基础上加了 text-embedding-v4 语义检索，用 RRF 融合两种结果，建了 16 题评测集，Hybrid Recall@8 做到 84.4%，0 failure。

**2 分钟版**：
1. 动机：keyword 对口语化问句差，需要语义检索补
2. 技术：text-embedding-v4（1024d）+ 余弦相似度 + RRF(k=20)
3. 策略：keyword 优先（省 API 成本，4 条以上不调 embedding），不足时兜底
4. 评测：16 题 × 5 种题型，三路对比。Hybrid 最优但和纯 Embedding 持平——说明 keyword 在收紧 KW_MIN_SCORE 后只当安全网
5. 反思：Reranking 缺失（检索结果可以后续重新排序），V5 会补

## 7. 我踩过的坑

1. **KW_MIN_SCORE=2 太宽**——keyword 假命中（Q9/Q16 分数低但被返回），调高到 6 后问题消失
2. **同一文件的 6 个 chunk 占满 top-8**——其他文件结果被挤掉，增加 per-file dedup（`MAX_CHUNKS_PER_FILE=2`）
3. **评测集空有预期文件缺少关键词验证**——新增 sanity_check 三步：源文件存在性 + 关键词存在性 + ground truth 覆盖
4. **`finish_reason` 是 MagicMock 对象**——trace 写入时 `json.dumps()` 失败（测试环境 mock 数据与 trace 管线隔离不足）
