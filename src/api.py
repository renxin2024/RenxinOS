"""Renxin OS HTTP API。"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from scalar_fastapi import get_scalar_api_reference

from src.agent import RETRIEVE_TOP_K, ask_agent_with_meta

app = FastAPI(
    title="Renxin OS",
    description="基于个人笔记的 RAG 问答 API",
    version="0.1.0",
    docs_url=None,
)


@app.get("/scalar", include_in_schema=False)
async def scalar_html():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
    )


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    top_k: int | None = Field(None, ge=1, le=20, description="检索块数量，默认 8")


class SourceItem(BaseModel):
    file: str
    heading: str
    score: int


class ChatTimings(BaseModel):
    retrieve_ms: float = Field(..., description="关键词检索耗时（毫秒）")
    prompt_ms: float = Field(..., description="拼装 system prompt 耗时（毫秒）")
    llm_ms: float = Field(..., description="LLM 调用耗时（毫秒）")
    total_ms: float = Field(..., description="端到端总耗时（毫秒）")


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    timings: ChatTimings


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")

    top_k = body.top_k if body.top_k is not None else RETRIEVE_TOP_K
    result = ask_agent_with_meta(question, top_k=top_k)
    return ChatResponse(**result)
