#!/usr/bin/env python3
"""
Renxin OS — Agent 核心模块
ask_agent(): 检索笔记 chunks → 拼 prompt → 调用 LLM 回答
"""

import json
import os
import re
from pathlib import Path

import jieba
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("DASHSCOPE_BASE_URL"),
)
DEFAULT_MODEL = os.getenv("DASHSCOPE_MODEL", "qwen3.6-plus-2026-04-02")

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CHUNKS_PATH = DATA_DIR / "chunks.json"
RETRIEVE_TOP_K = 8
MAX_CHUNK_CHARS = 600

# 问句关键词 → 笔记常用表述（弥补 keyword 字面不匹配）
_QUERY_EXPANSIONS: dict[str, list[str]] = {
    "checkbox": ["打勾", "任务池", "projects", "全局任务池", "只改"],
    "勾选": ["checkbox", "打勾", "任务池"],
}

_chunks_cache: list[dict] | None = None

# 检索时过滤的虚词 / 问句噪声（中英文）
_STOP_WORDS = frozenset({
    "的", "了", "是", "在", "和", "与", "或", "有", "我", "你", "他", "她", "它",
    "这", "那", "哪", "什么", "如何", "怎么", "为什么", "请", "能", "会", "要",
    "吗", "呢", "吧", "啊", "就", "都", "也", "还", "很", "更", "最", "个", "一",
    "两", "三", "四", "五", "个", "位", "种", "些", "吗", "么", "被", "把", "对",
    "从", "到", "为", "以", "及", "等", "中", "上", "下", "里", "内", "外",
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "in", "on",
    "for", "and", "or", "it", "this", "that", "what", "how", "where", "when",
})

# 领域词：强制保留，避免被长度规则误杀
_KEEP_WORDS = frozenset({
    "gtd", "checkbox", "projects", "rag", "os", "abc", "smart", "defer",
})

# 领域词加入 jieba 词典，避免「全局任务池」等被切碎
_DOMAIN_WORDS = (
    "全局任务池", "任务池", "收件箱", "下一步行动", "今日执行",
    "checkbox", "projects", "obsidian", "renxin", "gtd",
)
for _word in _DOMAIN_WORDS:
    jieba.add_word(_word)


def load_chunks() -> list[dict]:
    """读取 data/chunks.json，首次加载后缓存在内存。"""
    global _chunks_cache
    if _chunks_cache is not None:
        return _chunks_cache

    if not CHUNKS_PATH.is_file():
        raise FileNotFoundError(
            f"知识库不存在: {CHUNKS_PATH}，请先运行 python -m src.ingest"
        )

    _chunks_cache = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    return _chunks_cache


def _tokenize(text: str) -> set[str]:
    """中英文混合分词，供 keyword 检索使用。"""
    text = text.lower()
    tokens: set[str] = set()

    # 英文 / 数字整词（checkbox、projects、gtd 等）
    for word in re.findall(r"[a-z0-9]+", text):
        if word in _STOP_WORDS:
            continue
        if word in _KEEP_WORDS or len(word) >= 2:
            tokens.add(word)

    # 中文：cut_for_search 适合检索（更细粒度，利于部分匹配）
    for word in jieba.cut_for_search(text):
        word = word.strip().lower()
        if not word:
            continue
        if word in _STOP_WORDS:
            continue
        # 跳过纯标点；单字中文一般噪声大，保留领域单字如「勾」可后续扩展
        if len(word) == 1 and not re.match(r"[a-z0-9]", word):
            continue
        tokens.add(word)

    return tokens


def _expand_query_tokens(query: str, base_tokens: set[str]) -> set[str]:
    """根据问句触发同义扩展，提升中文笔记检索召回。"""
    expanded = set(base_tokens)
    query_lower = query.lower()
    for trigger, extras in _QUERY_EXPANSIONS.items():
        if trigger in query_lower or trigger in base_tokens:
            expanded.update(extras)
    return expanded


def retrieve(query: str, top_k: int = 3) -> list[dict]:
    """
    基于 jieba 分词 + 词重叠打分的 keyword 检索。
    返回 top_k 个 chunk，每项含原字段 + score。
    """
    query_tokens = _expand_query_tokens(query, _tokenize(query))
    if not query_tokens:
        return []

    scored: list[dict] = []
    for chunk in load_chunks():
        content_tokens = _tokenize(chunk.get("content", ""))
        heading_tokens = _tokenize(chunk.get("heading", ""))
        file_tokens = _tokenize(chunk.get("file", ""))

        score = 0
        for token in query_tokens:
            if token in content_tokens:
                score += 1
            if token in heading_tokens:
                score += 2
            if token in file_tokens:
                score += 1

        if score > 0:
            hit = dict(chunk)
            hit["score"] = score
            scored.append(hit)

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def _format_references(hits: list[dict]) -> str:
    """把检索结果格式化为参考资料文本。"""
    if not hits:
        return "（未检索到相关资料）"

    parts: list[str] = []
    for index, hit in enumerate(hits, start=1):
        content = hit.get("content", "").strip()
        if len(content) > MAX_CHUNK_CHARS:
            content = content[:MAX_CHUNK_CHARS] + "…"
        parts.append(
            f"--- 资料 {index}：{hit.get('file', '')} / {hit.get('heading', '')} ---\n"
            f"{content}"
        )
    return "\n\n".join(parts)


def _build_system_prompt(hits: list[dict]) -> str:
    references = _format_references(hits)
    return (
        "你是 Renxin OS 助手，专门根据用户的个人笔记回答问题。\n"
        "规则：\n"
        "1. 仅根据下方「参考资料」回答，可引用原文要点。\n"
        "2. 若资料中有「铁律」、表格或明确条目，优先直接引用，不要替换为推测。\n"
        "3. 若资料不足以回答，明确说「笔记中未找到相关信息」。\n"
        "4. 不要编造参考资料中没有的内容。\n\n"
        f"【参考资料】\n{references}"
    )


def ask_agent(user_input: str, top_k: int = RETRIEVE_TOP_K) -> str:
    return ask_agent_with_meta(user_input, top_k=top_k)["answer"]


def ask_agent_with_meta(user_input: str, top_k: int = RETRIEVE_TOP_K) -> dict:
    """返回答案 + 检索来源，供 API 使用。"""
    hits = retrieve(user_input, top_k=top_k)
    system_prompt = _build_system_prompt(hits)

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
    )
    answer = response.choices[0].message.content
    sources = [
        {
            "file": hit.get("file", ""),
            "heading": hit.get("heading", ""),
            "score": hit.get("score", 0),
        }
        for hit in hits
    ]
    return {"answer": answer, "sources": sources}

