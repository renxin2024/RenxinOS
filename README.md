# Renxin OS

基于个人 Obsidian 笔记的 RAG 问答服务：把 `data/principle/` 下的 Markdown 切块入库，用**关键词 + Embedding 混合检索**召回相关片段，再调用大模型生成答案。

**V2 能力**：笔记入库 · jieba 关键词检索 · text-embedding-v4 语义检索 · RRF 混合检索 · 16 题评测集 + Recall@k · `POST /chat` 返回答案、来源与分阶段耗时 · [Scalar](http://127.0.0.1:8000/scalar) 交互式 API 文档。

---

## 项目简介

Renxin OS 是 Java 转型 AI / Agent 方向的作品集项目，当前版本聚焦「可评测的 RAG 检索质量」：

| 模块 | 说明 |
|------|------|
| `src/ingest.py` | 读取 `data/principle/*.md`，按标题切块，输出 `data/chunks.json` |
| `src/embedding.py` | 调用 DashScope text-embedding-v4 生成向量，缓存至 `data/embeddings.json` |
| `src/agent.py` | 关键词检索(jieba) + Embedding 语义检索 + RRF 混合融合，拼接 prompt 后调用 LLM |
| `src/api.py` | FastAPI 暴露 `/health`、`POST /chat`；`/scalar` 提供 API 调试页 |

数据流：

```
principle/*.md → ingest → chunks.json → [keyword + embedding] → RRF merge → LLM → answer + sources + timings
```

**当前不含**：LangGraph、MCP、前端 UI（见路线图 V3+）。

---

## 检索评测指标（V2）

16 题评测集（`data/eval_questions.json`），覆盖 5 种题型：single_hop / multi_hop / fuzzy / unanswerable / paraphrase。

| 检索模式 | Recall@8 | KW Score | 失败模式 |
|----------|----------|----------|----------|
| **Keyword only** | 61.5% | 71.3% | SEARCH_FAILURE × 3, SHOULD_REFUSE × 2, CONTEXT_INCOMPLETE × 2 |
| **Embedding only** | 84.4% | 82.5% | SHOULD_REFUSE × 1 |
| **Hybrid (keyword→embedding→RRF)** | 84.4% | 82.5% | 0 failure |

**关键调优**：KW_MIN_SCORE=6 消除关键词误触发；MAX_CHUNKS_PER_FILE=2 消除单文件堆叠；per-file dedup + sanity check 三项全绿。

复现：

```bash
# 关键词基线
python scripts/run_eval.py

# Embedding 基线
python scripts/run_embedding_eval.py

# 混合检索
python scripts/run_hybrid_eval.py

# 评测集质量检查（上线前必跑）
python scripts/eval_sanity_check.py
```

---

## 安装

### 环境要求

- Python **3.11**（见 `.python-version`）
- 阿里云百炼 / DashScope API Key（OpenAI 兼容接口）

### 1. 克隆并进入项目

```bash
cd ~/ai_brain/RenxinOS
```

### 2. 创建并激活虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate   # fish: source .venv/bin/activate.fish
pip install -r requirements.txt
```

### 3. 配置环境变量

在项目根目录创建 `.env`：

```env
DASHSCOPE_API_KEY=你的_API_Key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=deepseek-v4-flash

# 可选：API 监听地址
# RENXINOS_HOST=127.0.0.1
# RENXINOS_PORT=8000
```

### 4. 构建知识库 + 向量索引

```bash
# 切块
python -m src.ingest

# 生成 embedding 向量（首次需调用 API，约 1 分钟）
python -c "from src.embedding import build_embeddings; build_embeddings()"
```

成功后会生成 `data/chunks.json` 和 `data/embeddings.json`。

### 5. 运行测试（可选）

```bash
pytest
```

---

## 快速开始

### 启动 API 服务

```bash
source .venv/bin/activate
python -m src.main
```

终端会打印：

```
Renxin OS API → http://127.0.0.1:8000
API 调试文档 → http://127.0.0.1:8000/scalar
```

### 浏览器调试

打开 **http://127.0.0.1:8000/scalar**，在页面中：

1. 展开 `GET /health` → Execute，确认返回 `{"status":"ok"}`
2. 展开 `POST /chat` → 填写请求体，例如：

```json
{
  "question": "什么是4D工作法？"
}
```

3. Execute 后查看 `answer`、`sources`（检索到的笔记片段）与 `timings`（分阶段耗时）

### 命令行调用

```bash
# 健康检查
curl http://127.0.0.1:8000/health

# 问答（含混合检索 + 分阶段耗时）
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "GTD 任务 checkbox 只允许写在哪两个地方？"}' | python3 -m json.tool
```

### 更新笔记后重新入库

修改 `data/principle/` 下的 Markdown 后，重新执行：

```bash
python -m src.ingest
python -c "from src.embedding import build_embeddings; build_embeddings()"
```

服务无需改代码；若 API 已在运行，重启后即加载新数据。

---

## 验收用例

固定验收问句（与 `tests/test_agent.py` 中 `VALIDATION_QUERY` 一致）：

```
GTD 任务 checkbox 只允许写在哪两个地方？
```

**期望答案要点**（须引用笔记铁律，不得编造）：

1. **全局任务池**（`tasks/全局任务池.md`「今日执行」）
2. **projects/** 目录下的项目文件

笔记原文（`决策与执行速查.md` · 工具地图）：

> **铁律**：任务状态 **只改任务池 / projects**；日志 **只写总结**。

**2026-06-21 实测**（`POST /chat`，`top_k=8`，hybrid retrieval）：

| 字段 | 结果 |
|------|------|
| `answer` | 正确列出「全局任务池」与 `projects/` 两处，并引用铁律 |
| `sources` 首位命中 | `决策与执行速查.md` / 七、工具地图 |
| `timings` | retrieve_ms≈25 · llm_ms≈56000 · total_ms≈56000 |

---

## Demo 自检

| 检查项 | 命令 / 操作 | 结果（2026-06-21） |
|--------|-------------|-------------------|
| 单元测试 | `pytest` | **14 passed** |
| 健康检查 | `GET /health` | `200` · `{"status":"ok"}` |
| API 文档 | `GET /scalar` | `200` · Scalar 页可打开 |
| 问答接口 | `POST /chat` | `200` · 返回答案 + sources + timings |
| 空问题校验 | `POST /chat` `{"question":"   "}` | `400` |
| 评测集 | `python scripts/run_hybrid_eval.py` | Recall@8=84.4% · 0 failure |
| Sanity check | `python scripts/eval_sanity_check.py` | ✅ 三项全绿 |

---

## 项目结构

```
RenxinOS/
├── data/
│   ├── principle/         # 源笔记（Markdown）
│   ├── chunks.json        # ingest 产物（勿手改）
│   ├── embeddings.json    # embedding 向量缓存（勿手改）
│   └── eval_questions.json # 16 题评测集
├── src/
│   ├── ingest.py          # 入库脚本
│   ├── embedding.py       # text-embedding-v4 向量生成与检索
│   ├── agent.py           # 关键词+Embedding+RRF混合检索 + LLM
│   ├── api.py             # FastAPI 应用
│   └── main.py            # uvicorn 启动入口
├── scripts/
│   ├── run_eval.py        # 关键词基线评测
│   ├── run_embedding_eval.py # Embedding 基线评测
│   ├── run_hybrid_eval.py # 混合检索评测
│   └── eval_sanity_check.py # 评测集三项健全性检查
├── tests/
├── requirements.txt
└── README.md
```

---

## 版本历程

| 版本 | 日期 | 核心能力 |
|------|------|----------|
| **V1** | 2026-06-17 | jieba 关键词检索 + `/chat` + timings |
| **V2** | 2026-06-21 | + text-embedding-v4 · RRF 混合检索 · 16 题评测集 · Recall@8=84.4% |

---

## 相关文档

- 执行规格与版本路线图：`~/ai_brain/todo/tasks/projects/Agent开发学习计划/RenxinOS-执行规格.md`
- 原则笔记源目录：`data/principle/README.md`
