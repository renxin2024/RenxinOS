#!/usr/bin/env python3
"""
Renxin OS — Embedding 语义检索模块
功能：将文档 chunk 转为向量 → 用余弦相似度检索 → 解决关键词检索的口语化问题

核心概念：
- Embedding（嵌入）：把文本变成一组浮点数（向量），语义相近的文本向量距离近
- 余弦相似度（Cosine Similarity）：衡量两个向量方向是否一致，值域 [-1, 1]
  - 1 = 完全相同方向（语义最相似）
  - 0 = 正交（不相关）
  - -1 = 完全相反方向

类比 Java：
- Embedding 类似 Java 中的 hashCode()，但 hashCode 只管相等不相等，
  Embedding 能表达「有多相似」
- 余弦相似度类似 Java Comparator，但返回连续分数而非 -1/0/1
"""

import json                                    # JSON 读写
import os                                      # 环境变量读取
import time                                    # 计时
from pathlib import Path                       # 路径操作（比 os.path 更现代）

import numpy as np                             # 数值计算库（矩阵运算、向量操作）
from dotenv import load_dotenv                 # 读取 .env 文件中的环境变量
from openai import OpenAI                      # OpenAI SDK（DashScope 兼容此接口）

# load_dotenv(): 从项目根目录的 .env 文件加载环境变量
# 类比 Java: 类似 Spring 的 @Value 从 application.properties 读配置
load_dotenv()

# 创建 DashScope 客户端（使用 OpenAI SDK 的兼容模式）
# DashScope 提供了和 OpenAI 相同的 API 格式，所以可以复用 OpenAI SDK
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),    # 从 .env 读取 API 密钥
    base_url=os.getenv("DASHSCOPE_BASE_URL"),  # DashScope 的 API 地址
)

# --- 配置 ---
# EMBEDDING_MODEL: DashScope 的 embedding 模型名
# text-embedding-v4 是阿里最新的 embedding 模型，支持中文，向量质量更高
EMBEDDING_MODEL = "text-embedding-v4"

# EMBEDDING_DIMS: 向量维度（embedding 输出的浮点数个数）
# 1024 维是质量和速度的平衡点：太低（256）语义表达力不够，太高（2048）存储和计算慢
EMBEDDING_DIMS = 1024

# BATCH_SIZE: 每次 API 调用最多处理的文本数
# DashScope text-embedding-v3 限制单次最多 10 条
# 类比 Java: 类似分页查询的 pageSize
BATCH_SIZE = 10

# 路径配置
# Path(__file__).resolve(): 获取当前文件的绝对路径
# .parents[1]: 往上跳一级（src/ → 项目根目录）
# 类比 Java: Paths.get(getClass().getResource(".").toURI()).getParent().getParent()
_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_CHUNKS_PATH = _DATA_DIR / "chunks.json"                # 原始文档片段
_EMBEDDINGS_PATH = _DATA_DIR / "embeddings.json"         # 缓存的向量数据

# 内存缓存：避免每次调用都从磁盘读
_embeddings_cache: list[dict] | None = None


def _get_embedding(texts: list[str]) -> list[list[float]]:
    """
    调用 DashScope API 将文本列表转为向量列表。

    参数:
        texts: 文本列表，每条文本会被转为一个 1024 维的浮点数向量

    返回:
        向量列表，每个向量是 list[float]，长度 = EMBEDDING_DIMS

    类比 Java:
        类似调用某个微服务接口，传入字符串列表，返回 float[][] 矩阵
    """
    # client.embeddings.create(): 调用 embedding API
    # model: 指定模型名称
    # input: 要嵌入的文本列表
    # dimensions: 输出向量的维度（text-embedding-v3 支持自定义维度）
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        dimensions=EMBEDDING_DIMS,
    )
    # response.data: 返回结果列表，每个元素有 .embedding 属性
    # [item.embedding for item in ...]: 列表推导式提取所有向量
    return [item.embedding for item in response.data]


def build_embeddings() -> list[dict]:
    """
    为所有文档 chunk 生成 embedding 向量，并缓存到磁盘。

    流程:
        1. 读取 chunks.json（102 个文档片段）
        2. 对每个 chunk 的 content 调用 embedding API
        3. 将 {id, file, heading, content, embedding} 写入 embeddings.json
        4. 返回完整列表

    为什么要缓存:
        - API 调用要钱（虽然 embedding 很便宜）
        - 102 个 chunk 的 embedding 生成约需 5-10 秒
        - 缓存后下次直接读文件，毫秒级加载

    类比 Java:
        类似启动时从数据库加载数据到 Redis 缓存
    """
    print("Loading chunks...")

    # 读取所有文档片段
    # json.loads(): 把 JSON 字符串解析为 Python 对象
    chunks = json.loads(_CHUNKS_PATH.read_text(encoding="utf-8"))
    print(f"  Found {len(chunks)} chunks")

    # 为每个 chunk 生成 embedding
    # 分批处理：每次 BATCH_SIZE 条，避免单次 API 调用太大
    all_embeddings: list[dict] = []
    # range(0, n, step): 生成 0, step, 2*step, ... 的序列
    # 类比 Java: for (int i = 0; i < n; i += step)
    for i in range(0, len(chunks), BATCH_SIZE):
        # batch: 当前批次的 chunk 列表（切片语法）
        batch = chunks[i : i + BATCH_SIZE]

        # 提取每个 chunk 的内容文本
        # 拼接 file + heading + content 作为 embedding 输入
        # 这样文件名和标题的语义也会被编码进向量
        # 提取每条 chunk 的关键信息拼接为 embedding 输入
        # 不用 f-string 嵌套引号（Python < 3.12 不支持），改用变量提取
        texts = []
        for c in batch:
            file_name = c.get('file', '')
            heading = c.get('heading', '')
            content_text = c.get('content', '')
            texts.append(file_name + ' | ' + heading + ' | ' + content_text)

        # 调用 API 获取向量
        vectors = _get_embedding(texts)

        # 将原始 chunk 数据和对应的向量合并
        for chunk, vector in zip(batch, vectors):
            # zip(): 将两个列表按位置配对，类似 Java 的 IntStream 遍历两个数组
            entry = dict(chunk)            # 复制 chunk 的所有字段
            entry["embedding"] = vector    # 新增 embedding 字段
            all_embeddings.append(entry)

        # 打印进度
        done = min(i + BATCH_SIZE, len(chunks))
        print(f"  Embedded {done}/{len(chunks)} chunks")

    # 缓存到磁盘（下次启动直接读文件，不再调 API）
    # json.dumps(..., ensure_ascii=False): 中文不转义为 \uXXXX
    _EMBEDDINGS_PATH.write_text(
        json.dumps(all_embeddings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  Saved to {_EMBEDDINGS_PATH}")

    return all_embeddings


def load_embeddings() -> list[dict]:
    """
    加载 embedding 数据：优先从缓存文件读，没有则重新生成。

    类比 Java:
        类似 getOrCreate() 模式——先看缓存有没有，没有就创建
    """
    # global: 声明要在函数内修改全局变量（Python 默认只能读全局变量）
    # 类比 Java: 不需要，Java 的 static 字段可以直接在方法中修改
    global _embeddings_cache

    # 如果内存缓存已存在，直接返回（最快路径）
    if _embeddings_cache is not None:
        return _embeddings_cache

    # 如果磁盘缓存存在，从文件加载
    if _EMBEDDINGS_PATH.is_file():
        _embeddings_cache = json.loads(
            _EMBEDDINGS_PATH.read_text(encoding="utf-8")
        )
        return _embeddings_cache

    # 都没有：调用 API 重新生成
    _embeddings_cache = build_embeddings()
    return _embeddings_cache


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    计算两个向量的余弦相似度。

    公式: cos(θ) = (a · b) / (|a| * |b|)
    - a · b: 点积（对应位置相乘再求和）
    - |a|: 向量的模（各元素平方和的平方根）

    返回值: [-1, 1]
    - 1 = 方向完全相同（语义最相似）
    - 0 = 正交（不相关）
    - -1 = 方向完全相反

    类比 Java:
        类似自己实现一个 distance 方法，但返回值是相似度而非距离
    """
    # np.array(): 将 Python list 转为 NumPy 数组（支持向量化运算）
    # 类比 Java: 类似把 double[] 包装成支持矩阵运算的对象
    vec_a = np.array(a)
    vec_b = np.array(b)

    # np.dot(): 点积运算（对应位置相乘再求和）
    # 类比 Java: 需要自己写 for 循环累加
    dot_product = np.dot(vec_a, vec_b)

    # np.linalg.norm(): 计算向量的模（L2 范数）
    # 公式: sqrt(x1^2 + x2^2 + ... + xn^2)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    # 防止除以零（空向量或全零向量的模为 0）
    if norm_a == 0 or norm_b == 0:
        return 0.0

    # 余弦相似度 = 点积 / (模A * 模B)
    return float(dot_product / (norm_a * norm_b))


def retrieve_semantic(query: str, top_k: int = 8) -> list[dict]:
    """
    基于 embedding 的语义检索。

    流程:
        1. 将用户问题转为向量
        2. 计算该向量与所有 chunk 向量的余弦相似度
        3. 按相似度降序排列，返回 top_k 个

    参数:
        query: 用户的提问文本
        top_k: 返回最相似的前 k 个结果

    返回:
        list[dict]，每个 dict 包含 file, heading, content, score, embedding
        格式与 keyword 检索的 retrieve() 一致，方便评测脚本直接复用

    类比 Java:
        类似在数据库中执行全文检索，但这里用的是向量相似度而非关键词匹配
    """
    # 确保 embedding 数据已加载
    embeddings = load_embeddings()

    # 将用户问题转为向量（只有一条，不需要分批）
    query_vector = _get_embedding([query])[0]

    # 计算 query 与每个 chunk 的相似度
    scored: list[dict] = []
    for entry in embeddings:
        # 取出 chunk 的 embedding 向量
        chunk_vector = entry.get("embedding", [])
        if not chunk_vector:
            continue

        # 计算余弦相似度
        score = _cosine_similarity(query_vector, chunk_vector)

        # 构造结果（复制原始字段 + 添加 score）
        hit = dict(entry)
        hit["score"] = score
        scored.append(hit)

    # 按相似度降序排列（分数越高越相似）
    # key=lambda item: item["score"]: 排序依据是 score 字段
    # reverse=True: 降序（从高到低）
    # 类比 Java: list.sort(Comparator.comparingDouble(Hit::getScore).reversed())
    scored.sort(key=lambda item: item["score"], reverse=True)

    # 去重：每个文件最多保留 MAX_CHUNKS_PER_FILE 个 chunk
    # 防止同一文件的多个 chunk 把 top-k 位置全占满，导致其他文件的内容被挤出去
    # 类比 Java: 类似 Stream.distinct() 但按 file 字段分组限制数量
    MAX_CHUNKS_PER_FILE = 2          # 每个文件最多贡献 2 个 chunk 到结果
    file_count: dict[str, int] = {}  # 记录每个文件已出现的 chunk 数
    deduped: list[dict] = []
    for hit in scored:
        file_name = hit.get("file", "")
        count = file_count.get(file_name, 0)
        if count < MAX_CHUNKS_PER_FILE:
            deduped.append(hit)
            file_count[file_name] = count + 1
        if len(deduped) >= top_k:
            break

    return deduped
