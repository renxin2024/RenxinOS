#!/usr/bin/env python3
"""
Renxin OS — Agent 核心模块
ask_agent(): 调用 LLM API 回答问题（无 RAG 的基础版本）
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("DASHSCOPE_BASE_URL"),
)


def ask_agent(user_input: str) -> str:
    response = client.chat.completions.create(
        model="qwen-turbo",
        messages=[{"role": "user", "content": user_input}]
    )
    return response.choices[0].message.content
