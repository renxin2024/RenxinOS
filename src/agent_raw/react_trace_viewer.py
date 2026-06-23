#!/usr/bin/env python3
"""
react_trace_viewer — ReAct 循环可视化

读取 data/react_traces.jsonl，生成 data/react_trace_viewer.html，
展示每次 run_react 的完整 prompt / raw_output / observation 交互链。

用法：
    python -m src.agent_raw.react_trace_viewer
    然后浏览器打开 data/react_trace_viewer.html
"""

import json
from pathlib import Path

TRACE_PATH = Path(__file__).resolve().parents[2] / "data" / "react_traces.jsonl"
HTML_PATH = Path(__file__).resolve().parents[2] / "data" / "react_trace_viewer.html"


def load_traces() -> list:
    """读取所有 trace 记录（JSONL），最新在前。"""
    if not TRACE_PATH.exists():
        return []
    traces = []
    with open(TRACE_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                traces.append(json.loads(line))
    traces.reverse()
    return traces


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ReAct Trace Viewer</title>
<style>
:root {
    --bg: #1e1e2e;
    --surface: #2a2a3e;
    --border: #44475a;
    --text: #cdd6f4;
    --muted: #a6adc8;
    --accent: #89b4fa;
    --green: #a6e3a1;
    --red: #f38ba8;
    --yellow: #f9e2af;
    --orange: #fab387;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 24px;
}
h1 { color: var(--accent); margin-bottom: 8px; font-size: 1.5rem; }
.summary { color: var(--muted); margin-bottom: 24px; font-size: 0.9rem; }
.trace {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 20px;
    overflow: hidden;
}
.trace-header {
    padding: 12px 16px;
    background: rgba(137,180,250,0.08);
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    user-select: none;
}
.trace-header:hover { background: rgba(137,180,250,0.15); }
.trace-header h2 { font-size: 1rem; color: var(--accent); display: flex; align-items: center; gap: 8px; }
.trace-header .arrow { transition: transform 0.2s; font-size: 0.8rem; }
.trace-header.open .arrow { transform: rotate(90deg); }
.trace-body { display: none; padding: 16px; }
.trace-body.open { display: block; }
.question {
    background: rgba(166,227,161,0.1);
    border-left: 3px solid var(--green);
    padding: 8px 12px;
    margin-bottom: 16px;
    border-radius: 0 4px 4px 0;
}
.step {
    margin-bottom: 16px;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
}
.step-header {
    padding: 8px 12px;
    background: rgba(249,226,175,0.08);
    border-bottom: 1px solid var(--border);
    font-weight: 600;
    color: var(--yellow);
    font-size: 0.9rem;
}
.step-body { padding: 12px; }
.field { margin-bottom: 12px; }
.field-label {
    font-size: 0.8rem;
    color: var(--muted);
    text-transform: uppercase;
    margin-bottom: 4px;
    font-weight: 600;
}
.field-content {
    background: var(--bg);
    padding: 10px;
    border-radius: 4px;
    font-family: "Fira Code", "Cascadia Code", monospace;
    font-size: 0.85rem;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 400px;
    overflow-y: auto;
    border: 1px solid var(--border);
}
.action { color: var(--orange); }
.observation { color: var(--green); }
.final-answer {
    color: var(--green);
    font-weight: 600;
    font-size: 1.1rem;
    padding: 12px;
    background: rgba(166,227,161,0.08);
    border-radius: 4px;
    border-left: 3px solid var(--green);
    margin-top: 12px;
}
.empty { text-align: center; color: var(--muted); padding: 60px; font-size: 1.1rem; }
.meta { color: var(--muted); font-size: 0.8rem; margin-top: 4px; }
.raw-toggle {
    font-size: 0.8rem;
    color: var(--muted);
    cursor: pointer;
    user-select: none;
    margin-bottom: 8px;
}
.raw-toggle:hover { color: var(--text); }
.raw-content { display: none; margin-bottom: 12px; }
.raw-content.open { display: block; }
</style>
</head>
<body>
<h1>ReAct Trace Viewer</h1>
<p class="summary">数据源：data/react_traces.jsonl</p>
<div id="container"></div>
<script>
const traces = __DATA_PLACEHOLDER__;
const container = document.getElementById('container');
document.querySelector('.summary').textContent = `共 ${traces.length} 条 trace 记录 · 数据源：data/react_traces.jsonl`;

if (traces.length === 0) {
    container.innerHTML = '<div class="empty">暂无 trace 记录。<br>运行 python -m src.agent_raw.react_loop 后刷新此页面。</div>';
} else {
    traces.forEach((trace, idx) => {
        const traceEl = document.createElement('div');
        traceEl.className = 'trace';

        const header = document.createElement('div');
        header.className = 'trace-header';
        header.innerHTML = `<h2><span class="arrow">▶</span> Trace #${idx + 1}：${escapeHtml(trace.question)}</h2>
            <div class="meta">model: ${trace.model} · trace_id: ${trace.trace_id} · steps: ${trace.steps.length}</div>`;
        header.onclick = () => {
            header.classList.toggle('open');
            body.classList.toggle('open');
        };
        traceEl.appendChild(header);

        const body = document.createElement('div');
        body.className = 'trace-body';

        body.innerHTML += `<div class="question"><strong>Question:</strong> ${escapeHtml(trace.question)}</div>`;

        trace.steps.forEach(step => {
            let stepHtml = `<div class="step">
                <div class="step-header">Step ${step.step}</div>
                <div class="step-body">
                    <div class="field"><div class="field-label">Thought</div><div class="field-content">${escapeHtml(step.thought || '')}</div></div>`;
            if (step.action) {
                stepHtml += `<div class="field"><div class="field-label">Action</div><div class="field-content action">${escapeHtml(step.action)}</div></div>
                    <div class="field"><div class="field-label">Action Input</div><div class="field-content">${escapeHtml(step.action_input || '')}</div></div>`;
            }
            if (step.observation) {
                stepHtml += `<div class="field"><div class="field-label">Observation</div><div class="field-content observation">${escapeHtml(step.observation)}</div></div>`;
            }
            if (step.final_answer) {
                stepHtml += `<div class="final-answer">Final Answer: ${escapeHtml(step.final_answer)}</div>`;
            }
            // Raw prompt toggle
            if (step.prompt) {
                stepHtml += `<div class="raw-toggle" onclick="this.nextElementSibling.classList.toggle('open'); this.textContent = this.nextElementSibling.classList.contains('open') ? '▼ 收起原始 Prompt' : '▶ 查看原始 Prompt'">▶ 查看原始 Prompt</div>
                    <div class="raw-content"><div class="field"><div class="field-label">Prompt (sent to LLM)</div><div class="field-content">${escapeHtml(step.prompt)}</div></div></div>`;
            }
            if (step.raw_output) {
                stepHtml += `<div class="raw-toggle" onclick="this.nextElementSibling.classList.toggle('open'); this.textContent = this.nextElementSibling.classList.contains('open') ? '▼ 收起原始输出' : '▶ 查看原始 LLM 输出'">▶ 查看原始 LLM 输出</div>
                    <div class="raw-content"><div class="field"><div class="field-label">Raw LLM Output</div><div class="field-content">${escapeHtml(step.raw_output)}</div></div></div>`;
            }
            stepHtml += `</div></div>`;
            body.innerHTML += stepHtml;
        });

        if (trace.final_answer) {
            body.innerHTML += `<div class="final-answer">最终答案：${escapeHtml(trace.final_answer)}</div>`;
        }

        traceEl.appendChild(body);
        container.appendChild(traceEl);
    });

    // Auto-expand first trace
    const firstHeader = container.querySelector('.trace-header');
    const firstBody = container.querySelector('.trace-body');
    if (firstHeader && firstBody) {
        firstHeader.classList.add('open');
        firstBody.classList.add('open');
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
</script>
</body>
</html>"""


def generate_html(traces: list) -> str:
    """生成带交互展示的 HTML 字符串。"""
    data_json = json.dumps(traces, ensure_ascii=False, indent=2)
    return HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json)


def main():
    traces = load_traces()
    html = generate_html(traces)
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"已生成 {HTML_PATH}（共 {len(traces)} 条 trace）")
    print(f"浏览器打开：file://{HTML_PATH}")


if __name__ == "__main__":
    main()
