# V1：Keyword RAG — 从零搭建一个能问答的检索系统

> 代码路径：`src/ingest.py`、`src/agent.py`（keyword 分支）、`src/api.py`、`src/main.py`
> 验收清单：`~/ai_brain/todo/tasks/projects/Agent开发学习计划/RenxinOS-验收清单.md#V1（6/17）`

## 1. 为什么需要它

Java 后台程序员转型 AI/Agent 方向，第一步不是学模型，而是搭建一个「输入问题 → 检索知识 → 喂给 LLM → 输出答案」的闭环。

不用它会出现的问题：
- 每次问 LLM 都依赖瞬时记忆（模型可能记不住你的笔记内容）
- 你的个人笔记没有变成系统能力——笔记在 Obsidian 里，AI 访问不到

## 2. 第一性原理

RAG（Retrieval-Augmented Generation）的核心输入输出：

| 组件 | 输入 | 输出 |
|---|---|---|
| Ingest（入库） | Markdown 笔记 | chunks.json（按标题切块） |
| Retrieve（检索） | 用户问题 | top-k 个最相关的 chunk |
| Augment（拼装） | chunks + 问题 | system prompt（含引用来源） |
| Generate（生成） | prompt | 答案 + 来源 |

类比你熟悉的 Java 三层架构：
- Ingest = 数据入库（类似 ETL 的 E）
- Retrieve = DAO 层的 `findByKeyword()`
- Augment = Service 层拼 DTO
- Generate = 调用外部 API

## 3. 最小代码

| 模块 | 文件 | 核心逻辑 |
|---|---|---|
| 切块入库 | `src/ingest.py` | 按 `#/##/###` 标题拆文件 → `data/chunks.json` |
| 关键词分词 | `src/agent.py:_tokenize()` | jieba 中文分词 + 英文保留 + 领域词字典 |
| 关键词检索 | `src/agent.py:retrieve()` | 问题 vs chunk 关键词重叠数 → 按分数排序 |
| HTTP API | `src/api.py` | FastAPI `/health` + `POST /chat` |
| 启动入口 | `src/main.py` | uvicorn 绑定 `127.0.0.1:8000` |

## 4. 运行轨迹

```
Q: "GTD 任务 checkbox 只允许写在哪两个地方？"
↓
1. ingest: 读 data/principle/*.md → 102 chunks
2. _tokenize("GTD 任务 checkbox...") → {"gtd","checkbox","任务","写","地方"}
3. retrieve: 102 chunks × 关键词重叠 = 每个 chunk 一个分数
4. top-3: 决策与执行速查.md#工具地图(8分) + 全局任务池.md#前言(5分) + ...
5. _build_system_prompt: 拼接参考资料 → "根据以下笔记回答，只引用笔记内容..."
6. LLM: deepseek-v4-flash → 答案 + sources
```

## 5. 与框架的对应关系

| 手写 V1 | LangChain / 框架概念 |
|---|---|
| `chunk_markdown()` | LangChain `MarkdownHeaderTextSplitter` |
| `_tokenize()` + `retrieve()` | LangChain `KeywordRetriever` / BM25 |
| `_build_system_prompt()` | LangChain `ChatPromptTemplate` |
| `OpenAI().chat.completions.create()` | LangChain `ChatOpenAI` |

## 6. 面试讲法

**30 秒版**：用 jieba 分词做了个人知识库的 keyword RAG，把 Obsidian 笔记切块入库，通过关键词重叠打分检索，拼到 prompt 里喂给 DashScope LLM 回答。

**2 分钟版**：
1. 背景：Java 转向 Python AI，从最基础的 RAG 开始。
2. 架构：ingest → retrieve → augment → generate 四步闭环。
3. 选型：jieba（无需训练，中文支持好）+ DashScope API（OpenAI 兼容，迁移成本低）。
4. 验证：固定验收问句「GTD checkbox 写在哪」跑通端到端。
5. 反思：keyword 对口语化问句不友好（"打勾"搜不到"checkbox"），V2 会加 embedding。

## 7. 我踩过的坑

1. **jieba 把"全局任务池"切成四个词**——解决方案：`jieba.add_word()` 注册领域词典。
2. **停用词过滤太激进删掉了"不"字**——导致否定语义丢失，后来停用词只删虚词保留否定词。
3. **`_tokenize()` 里 `set` 是无序的**——对检索没影响但导致测试期望不稳定，评测脚本用 Recall@k 不用顺序断言。
