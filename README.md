# Renxin OS

基于个人 Obsidian 笔记的 RAG 问答服务：把 `data/principle/` 下的 Markdown 切块入库，用关键词检索召回相关片段，再调用大模型生成答案。

**V1 能力**：笔记入库 · jieba 关键词检索 · `POST /chat` 返回答案与来源 · [Scalar](http://127.0.0.1:8000/scalar) 交互式 API 文档。

---

## 项目简介

Renxin OS 是 Java 转型 AI / Agent 方向的作品集项目，当前版本聚焦「知识库 RAG 最小闭环」：

| 模块 | 说明 |
|------|------|
| `src/ingest.py` | 读取 `data/principle/*.md`，按标题切块，输出 `data/chunks.json` |
| `src/agent.py` | jieba 分词 + 词重叠检索，拼接 prompt 后调用 DashScope（OpenAI 兼容 API） |
| `src/api.py` | FastAPI 暴露 `/health`、`POST /chat`；`/scalar` 提供 API 调试页 |

数据流：

```
principle/*.md  →  ingest  →  chunks.json  →  retrieve  →  LLM  →  answer + sources
```

**当前不含**：Embedding 向量检索、LangGraph、MCP、前端 UI（见路线图 V2+）。

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

### 4. 构建知识库

```bash
python -m src.ingest
```

成功后会生成 `data/chunks.json`，终端输出切块数量。

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

3. Execute 后查看 `answer` 与 `sources`（检索到的笔记片段）

### 命令行调用

```bash
# 健康检查
curl http://127.0.0.1:8000/health

# 问答
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "GTD 任务 checkbox 只允许写在哪两个地方？"}' | python3 -m json.tool
```

### 更新笔记后重新入库

修改 `data/principle/` 下的 Markdown 后，重新执行：

```bash
python -m src.ingest
```

服务无需改代码；若 API 已在运行，重启后 `agent` 会加载新的 `chunks.json`（进程内会缓存，重启即刷新）。

---

## 验收用例（V1）

固定验收问句（与 `tests/test_agent.py` 中 `VALIDATION_QUERY` 一致）：

```
GTD 任务 checkbox 只允许写在哪两个地方？
```

**期望答案要点**（须引用笔记铁律，不得编造）：

1. **全局任务池**（`tasks/全局任务池.md`「今日执行」）
2. **projects/** 目录下的项目文件

笔记原文（`决策与执行速查.md` · 工具地图）：

> **铁律**：任务状态 **只改任务池 / projects**；日志 **只写总结**。

**2026-06-16 实测**（`POST /chat`，`top_k=8`）：

| 字段 | 结果 |
|------|------|
| `answer` | 正确列出「全局任务池」与 `projects/` 两处，并引用铁律 |
| `sources` 首位命中 | `决策与执行速查.md` / 七、工具地图（去哪改什么） |
| 检索扩展 | `checkbox` 问句自动扩展 `打勾`、`任务池`、`projects` 等同义词 |

复现：

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "GTD 任务 checkbox 只允许写在哪两个地方？"}' | python3 -m json.tool
```

---

## Demo 自检

| 检查项 | 命令 / 操作 | 结果（2026-06-16） |
|--------|-------------|-------------------|
| 单元测试 | `pytest` | **14 passed** |
| 健康检查 | `GET /health` | `200` · `{"status":"ok"}` |
| API 文档 | `GET /scalar` | `200` · Scalar 页可打开 |
| 问答接口 | `POST /chat` | `200` · 返回答案 + sources |
| 空问题校验 | `POST /chat` `{"question":"   "}` | `400` |

---

## 项目结构

```
RenxinOS/
├── data/
│   ├── principle/     # 源笔记（Markdown）
│   └── chunks.json      # ingest 产物（勿手改）
├── src/
│   ├── ingest.py        # 入库脚本
│   ├── agent.py         # 检索 + LLM
│   ├── api.py           # FastAPI 应用
│   └── main.py          # uvicorn 启动入口
├── tests/
├── requirements.txt
└── README.md
```

---

## 相关文档

- 执行规格与版本路线图：`~/ai_brain/todo/tasks/projects/Agent开发学习计划/RenxinOS-执行规格.md`
- 原则笔记源目录：`data/principle/README.md`
