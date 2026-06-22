"""Renxin OS HTTP API。"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from scalar_fastapi import get_scalar_api_reference

from src.agent import RETRIEVE_TOP_K, ask_agent_with_meta
from src.trace import load_traces

app = FastAPI(
    title="Renxin OS",
    description="基于个人笔记的 RAG 问答 API",
    version="0.2.0",
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
    score: float


class ChatTimings(BaseModel):
    retrieve_ms: float = Field(..., description="检索耗时（毫秒，含 keyword+embedding 混合检索）")
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


@app.get("/traces", response_class=HTMLResponse)
def traces_page():
    """Trace 可视化页面：展示每次 /chat 请求的完整调用链。"""
    traces = load_traces(limit=50)
    # 注入 trace 数据到 HTML 模板
    html = _build_traces_html(traces)
    return HTMLResponse(content=html)


@app.get("/api/traces")
def api_traces(limit: int = 50):
    """Trace JSON API：供外部工具消费。"""
    return load_traces(limit=limit)


def _build_traces_html(traces: list[dict]) -> str:
    """构建 trace 可视化 HTML 页面。"""
    import json
    traces_json = json.dumps(traces, ensure_ascii=False)
    return TRACES_HTML_TEMPLATE.replace("{{TRACES_DATA}}", traces_json)


# HTML 模板：内嵌 CSS + JS，零外部依赖，浏览器直接打开
TRACES_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Renxin OS — Pipeline Trace Viewer</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0d1117; color: #c9d1d9; padding: 24px; }
h1 { color: #58a6ff; margin-bottom: 8px; font-size: 20px; }
.subtitle { color: #8b949e; margin-bottom: 24px; font-size: 13px; }
.trace-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; margin-bottom: 16px; overflow: hidden; }
.trace-header { padding: 12px 16px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
.trace-header:hover { background: #1c2333; }
.trace-id { font-family: monospace; color: #79c0ff; font-size: 13px; }
.trace-query { color: #e6edf3; font-size: 14px; flex: 1; margin: 0 12px; }
.trace-time { color: #8b949e; font-size: 12px; }
.trace-meta { display: flex; gap: 16px; font-size: 12px; color: #8b949e; margin-top: 4px; }
.trace-steps { display: none; border-top: 1px solid #30363d; padding: 12px 16px; }
.trace-card.open .trace-steps { display: block; }
.step { margin-bottom: 12px; padding: 8px 12px; background: #0d1117; border-radius: 6px; border-left: 3px solid #30363d; }
.step.keyword_retrieve { border-left-color: #f0883e; }
.step.embedding_retrieve { border-left-color: #a371f7; }
.step.rrf_merge { border-left-color: #3fb950; }
.step.hybrid_decision { border-left-color: #58a6ff; }
.step.build_prompt { border-left-color: #d2a8ff; }
.step.llm_call { border-left-color: #f778ba; }
.step-name { font-family: monospace; font-size: 13px; font-weight: 600; margin-bottom: 4px; }
.step-elapsed { float: right; font-size: 12px; color: #8b949e; }
.step-data { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 12px; }
.step-data label { color: #8b949e; font-size: 11px; text-transform: uppercase; }
.step-data code { color: #e6edf3; background: #1c2333; padding: 1px 4px; border-radius: 3px; font-size: 12px; }
.waterfall { margin-top: 8px; }
.waterfall-bar { height: 6px; border-radius: 3px; margin-bottom: 2px; position: relative; }
.waterfall-bar span { position: absolute; right: 4px; top: -14px; font-size: 10px; color: #8b949e; }
.badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge-kw { background: #f0883e22; color: #f0883e; }
.badge-em { background: #a371f722; color: #a371f7; }
.badge-rrf { background: #3fb95022; color: #3fb950; }
.empty { text-align: center; padding: 48px; color: #8b949e; }
</style>
</head>
<body>
<h1>Renxin OS Pipeline Trace Viewer</h1>
<p class="subtitle">每次 /chat 请求的完整调用链追踪 · 点击展开详情</p>
<div id="traces"></div>
<script>
const traces = {{TRACES_DATA}};
const container = document.getElementById('traces');
if (!traces.length) {
    container.innerHTML = '<div class="empty">暂无 trace 记录<br>发送一次 POST /chat 请求后刷新此页面</div>';
}
traces.forEach(t => {
    const card = document.createElement('div');
    card.className = 'trace-card';
    // 判断走哪条路径
    const decisions = t.steps.filter(s => s.step === 'hybrid_decision');
    const lastDecision = decisions[decisions.length - 1];
    const route = lastDecision ? lastDecision.output.decision : 'unknown';
    const routeBadge = route === 'keyword_only' ? '<span class="badge badge-kw">KW</span>'
        : route === 'embedding_only' ? '<span class="badge badge-em">EM</span>'
        : route === 'rrf_merged' ? '<span class="badge badge-rrf">RRF</span>'
        : route;
    const totalMs = t.output && t.output.timings ? t.output.timings.total_ms : 0;
    card.innerHTML = `
        <div class="trace-header" onclick="this.parentElement.classList.toggle('open')">
            <span class="trace-id">#${t.trace_id}</span>
            <span class="trace-query">${escHtml(t.query)}</span>
            ${routeBadge}
            <span class="trace-time">${Math.round(totalMs)}ms</span>
        </div>
        <div class="trace-meta" style="padding:0 16px 8px">${t.timestamp} · ${t.steps.length} steps · answer ${t.output?t.output.answer_length:0} chars</div>
        <div class="trace-steps">
            ${t.steps.map(renderStep).join('')}
            ${renderWaterfall(t)}
        </div>
    `;
    container.appendChild(card);
});
function renderStep(s) {
    return `<div class="step ${s.step}">
        <div class="step-name">${s.step} <span class="step-elapsed">${s.elapsed_ms}ms</span></div>
        <div class="step-data">
            <div><label>Input</label><br>${renderData(s.input)}</div>
            <div><label>Output</label><br>${renderData(s.output)}</div>
        </div>
    </div>`;
}
function renderData(d) {
    if (!d) return '-';
    return Object.entries(d).map(([k,v]) => `<code>${escHtml(k)}=${escHtml(String(v))}</code>`).join(' ');
}
function renderWaterfall(t) {
    const steps = t.steps.filter(s => s.elapsed_ms > 1);
    if (!steps.length) return '';
    const maxMs = Math.max(...steps.map(s => s.elapsed_ms));
    const colors = {keyword_retrieve:'#f0883e', embedding_retrieve:'#a371f7', rrf_merge:'#3fb950', build_prompt:'#d2a8ff', llm_call:'#f778ba'};
    return `<div class="waterfall"><label style="font-size:11px;color:#8b949e;text-transform:uppercase">耗时瀑布图</label>
        ${steps.map(s => `<div class="waterfall-bar" style="width:${Math.max(2, s.elapsed_ms/maxMs*100)}%;background:${colors[s.step]||'#58a6ff'}"><span>${s.step} ${s.elapsed_ms}ms</span></div>`).join('')}
    </div>`;
}
function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
</script>
</body>
</html>"""
