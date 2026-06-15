#!/usr/bin/env python3
"""
Renxin OS — 知识库入库脚本
读取 data/principle/ 下的 Markdown 笔记，按 ## 标题切块 → 输出 data/chunks.json
"""

import json
import re
from pathlib import Path

# ── 路径计算 ──────────────────────────────────────────────
# __file__: 当前脚本的完整路径 (src/ingest.py)
# .resolve(): 解析符号链接，得到绝对路径
# .parents[1]: 取父目录的父目录，即项目根目录
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
NOTES_DIR = DATA_DIR / "principle"           # Markdown 笔记目录
OUTPUT_PATH = DATA_DIR / "chunks.json"       # 输出的知识库文件


def chunk_markdown(filepath: Path) -> list[dict]:
    """
    将一个 Markdown 文件按 ## 标题切块。

    策略：
    - 文件开头到第一个 ## 之前的内容 → 标题记为"前言"
    - 每个 # 或 ## 或 ### 标题 → 新块开始
    - 标题下的所有行归入该块，直到下一个同级/上级标题
    - 空块跳过
    """
    text = filepath.read_text(encoding="utf-8")
    filename = filepath.name

    chunks: list[dict] = []
    lines = text.split("\n")

    # 当前正在积累的块
    current_heading = "前言"   # 文件开头的默认标题
    current_lines: list[str] = []

    for line in lines:
        # 正则：行首 1~4 个 # + 空格 + 标题文字
        # 例: "# 核心概念" → match（一级标题）
        # 例: "## 核心原则" → match（二级标题）
        # 例: "##### 太深了" → 不匹配（5个#），归入当前块
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            # 遇到新标题 → 把之前积累的块保存
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:  # 跳过空块
                    chunks.append({
                        "id": f"{filename}#{current_heading}",  # 唯一标识
                        "file": filename,
                        "heading": current_heading,
                        "content": content,
                    })
            # 开始新块
            current_heading = m.group(2).strip()
            current_lines = []
        else:
            # 非标题行 → 归入当前块
            current_lines.append(line)

    # 文件末尾还有未保存的内容
    if current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            chunks.append({
                "id": f"{filename}#{current_heading}",
                "file": filename,
                "heading": current_heading,
                "content": content,
            })

    return chunks


def main():
    """遍历 principle 目录下所有 .md 文件，切块并输出"""
    all_chunks = []
    md_files = sorted(NOTES_DIR.glob("*.md"))  # 排序保证输出稳定

    for md_file in md_files:
        chunks = chunk_markdown(md_file)
        all_chunks.extend(chunks)

    # 写入 JSON（ensure_ascii=False 保留中文，indent=2 人类可读）
    OUTPUT_PATH.write_text(
        json.dumps(all_chunks, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"✅ {len(all_chunks)} 个知识块 → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
