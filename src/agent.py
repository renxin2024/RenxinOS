#!/usr/bin/env python3
"""
Renxin OS — Agent 核心模块
ask_agent(): 检索笔记 chunks → 拼 prompt → 调用 LLM 回答

检索策略：Hybrid（keyword 优先，不足时 embedding 兜底）
- keyword recall >= KW_RECALL_THRESHOLD 时直接返回，不调 embedding API
- keyword 不足时调用 text-embedding-v4 语义检索补充，通过 RRF 融合结果
"""

import json
import os
import re
import time
from pathlib import Path

import jieba
from dotenv import load_dotenv
from openai import OpenAI

# retrieve_semantic: 基于 text-embedding-v4 的语义检索，keyword 不足时兜底
# 只在需要时 import，避免冷启动时不必要的 embedding 模型加载
from src.embedding import retrieve_semantic, load_embeddings

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("DASHSCOPE_BASE_URL"),
)
DEFAULT_MODEL = os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash")

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CHUNKS_PATH = DATA_DIR / "chunks.json"
RETRIEVE_TOP_K = 8
MAX_CHUNK_CHARS = 600

# Hybrid 检索配置
# KW_RECALL_THRESHOLD: keyword 检索「足够好」的判定阈值
# - keyword 结果数 >= 此值 且 top-1 score >= KW_MIN_SCORE 时，直接返回不调 embedding
# - 类比 Java: 类似缓存命中率的 HIT_THRESHOLD，低于阈值才穿透到下一层
KW_RECALL_THRESHOLD = 4       # keyword 至少找到 4 个结果才算「够」
KW_MIN_SCORE = 6              # top-1 的关键词重叠分数至少为 6
# 调参记录：
#   v1: KW_MIN_SCORE=2 → Hybrid=67.7%（过宽，Q9/Q16 假命中）
#   v2: KW_MIN_SCORE=6 → 需评测验证（收紧后 Q9/Q16 强制走 embedding 路径）

# RRF 常数 k：防止排名靠前但分数很高的结果过度主导融合结果
# 论文推荐值 60，实践中个人知识库用小值（20）让排名影响更明显
_RRF_K = 20

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


def _rrf_merge(
    kw_hits: list[dict],
    em_hits: list[dict],
    top_k: int,
) -> list[dict]:
    """
    RRF（Reciprocal Rank Fusion）：将 keyword 和 embedding 两路结果融合为一路。

    核心公式: RRF_score(doc) = sum(1 / (k + rank_i))
    - rank_i: 该文档在第 i 路结果中的排名（从 1 开始）
    - k: 常数（_RRF_K = 20），防止排名 1 的结果分数过高

    为什么用排名而非原始分数:
    - keyword score 范围是整数（1~10+），embedding score 是浮点数（0~1）
    - 直接加权要先归一化，且不同查询的分布不同
    - 用排名规避了这个问题：排名 1 的就是最好的，不管原始分数是多少
    - 类比 Java: 类似 Comparator.comparingInt(rank) 而非 Comparator.comparingDouble(score)

    参数:
        kw_hits: keyword 检索结果，已按 score 降序
        em_hits: embedding 检索结果，已按 score 降序
        top_k: 返回前几个

    返回:
        融合后的结果列表，每项含 rrf_score 字段
    """
    # rrf_scores: dict，key = chunk 的唯一 id，value = 累计 RRF 分数
    # 类比 Java: Map<String, Double> rrfScores = new HashMap<>()
    rrf_scores: dict[str, float] = {}

    # chunk_map: 存储每个 id 对应的完整 chunk 数据（用于最终输出）
    chunk_map: dict[str, dict] = {}

    # 遍历两路结果，分别计算 RRF 贡献
    for hits in (kw_hits, em_hits):
        for rank, hit in enumerate(hits, start=1):
            # 用 id 字段作为文档唯一标识（chunks.json 中有 id 字段）
            doc_id = hit.get("id", hit.get("file", "") + "#" + hit.get("heading", ""))

            # RRF 公式: 1 / (k + rank)
            # enumerate 从 1 开始，所以 rank=1 是最相关的文档
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (_RRF_K + rank)

            # 保存 chunk 数据（keyword 和 embedding 可能有同一个 chunk，用任意一个都行）
            if doc_id not in chunk_map:
                chunk_map[doc_id] = hit

    # 按 RRF 分数降序排列，取前 top_k 个
    sorted_ids = sorted(rrf_scores, key=lambda x: -rrf_scores[x])
    results = []
    for doc_id in sorted_ids[:top_k]:
        hit = dict(chunk_map[doc_id])
        hit["rrf_score"] = rrf_scores[doc_id]   # 记录融合分数（方便调试）
        hit["score"] = rrf_scores[doc_id]        # 统一 score 字段，兼容下游代码
        results.append(hit)

    return results


def retrieve_hybrid(query: str, top_k: int = RETRIEVE_TOP_K) -> list[dict]:
    """
    Hybrid 检索：keyword 优先，不足时 embedding 兜底，通过 RRF 融合。

    策略（Cascade Retrieval）:
        1. 先跑 keyword 检索（本地运算，零 API 成本，毫秒级）
        2. 如果 keyword 结果足够好（数量 >= KW_RECALL_THRESHOLD 且 top-1 分数 >= KW_MIN_SCORE）
           → 直接返回，不调 embedding API
        3. 否则，补充调用 embedding 检索（有 API 成本，~200ms 延迟）
        4. 两路结果通过 RRF 融合，返回最终 top_k

    适用场景:
        - 精确术语查询（GTD、SMART、checkbox）→ keyword 通常能命中，embedding 不触发
        - 口语化/模糊查询（「手头事太多」）→ keyword 不足，触发 embedding 兜底

    类比 Java:
        类似二级缓存（L1 本地缓存 + L2 远程缓存）：
        先查 L1（快、免费），命中则返回；未命中才查 L2（慢、有成本）
    """
    # 第一步：keyword 检索（本地，零成本）
    # 注意：retrieve() 里的 top_k 参数控制返回数量，我们先要回 top_k 条再判断质量
    kw_hits = retrieve(query, top_k=top_k)

    # 第二步：判断 keyword 是否「足够好」
    # 条件：结果数量够 AND top-1 分数够高
    kw_good = (
        len(kw_hits) >= KW_RECALL_THRESHOLD
        and kw_hits[0].get("score", 0) >= KW_MIN_SCORE
    )

    if kw_good:
        # keyword 够用，直接返回（不调 embedding API，省钱省时间）
        return kw_hits

    # 第三步：keyword 不足，调用 embedding 语义检索兜底
    em_hits = retrieve_semantic(query, top_k=top_k)

    # 第四步：RRF 融合两路结果
    # 如果 keyword 完全没有结果，em_hits 就是全部；有部分结果则融合
    if not kw_hits:
        return em_hits  # keyword 完全没命中，直接返回 embedding 结果

    return _rrf_merge(kw_hits, em_hits, top_k=top_k)


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


def _elapsed_ms(start: float) -> float:
    """自 perf_counter 起点起的毫秒数（保留 1 位小数）。"""
    return round((time.perf_counter() - start) * 1000, 1)


def ask_agent(user_input: str, top_k: int = RETRIEVE_TOP_K) -> str:
    return ask_agent_with_meta(user_input, top_k=top_k)["answer"]


def ask_agent_with_meta(user_input: str, top_k: int = RETRIEVE_TOP_K) -> dict:
    """返回答案 + 检索来源 + 分阶段耗时，供 API 使用。"""
    total_start = time.perf_counter()

    retrieve_start = time.perf_counter()
    # retrieve_hybrid: keyword 优先，不足时 embedding 兜底（Cascade Retrieval）
    hits = retrieve_hybrid(user_input, top_k=top_k)
    retrieve_ms = _elapsed_ms(retrieve_start)

    prompt_start = time.perf_counter()
    system_prompt = _build_system_prompt(hits)
    prompt_ms = _elapsed_ms(prompt_start)

    llm_start = time.perf_counter()
    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
    )
    llm_ms = _elapsed_ms(llm_start)

    answer = response.choices[0].message.content
    sources = [
        {
            "file": hit.get("file", ""),
            "heading": hit.get("heading", ""),
            "score": hit.get("score", 0),
        }
        for hit in hits
    ]
    return {
        "answer": answer,
        "sources": sources,
        "timings": {
            "retrieve_ms": retrieve_ms,
            "prompt_ms": prompt_ms,
            "llm_ms": llm_ms,
            "total_ms": _elapsed_ms(total_start),
        },
    }

