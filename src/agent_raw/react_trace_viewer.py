#!/usr/bin/env python3
"""
react_trace_viewer — ReAct 循环可视化（S7 升级版）

读取 data/react_traces.jsonl，生成 data/react_trace_viewer.html，
展示每次 run_react 的完整交互链 + 性能分析（时间轴、耗时分解）。

用法：
    python -m src.agent_raw.react_trace_viewer
    然后浏览器打开 data/react_trace_viewer.html

S7 升级内容：
- 新增性能摘要卡片（总耗时/步数/平均/LLM合计/工具合计）
- 新增时间轴条形图（每步 LLM vs Tool 耗时对比）
- 每步 header 显示 LLM/工具/累计耗时
- 内联性能条形图（视觉化 LLM 与工具耗时占比）
- 全局统计摘要（总 trace 数/总步数/平均步数/平均耗时）
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
<title>ReAct Trace Viewer — 步骤日志与性能分析</title>
<style>
:root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --muted: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --red: #f85149;
    --yellow: #d2991d;
    --orange: #db6d28;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 24px;
    max-width: 1200px;
    margin: 0 auto;
}
h1 { color: var(--accent); margin-bottom: 8px; font-size: 1.5rem; }
.summary { color: var(--muted); margin-bottom: 24px; font-size: 0.9rem; }

/* ===== 性能摘要卡片 ===== */
.perf-summary {
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
}
.perf-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    min-width: 120px;
    flex: 1;
}
.perf-card .label { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; margin-bottom: 4px; letter-spacing: 0.5px; }
.perf-card .value { font-size: 1.15rem; font-weight: 700; }
.perf-card .value.green { color: var(--green); }
.perf-card .value.accent { color: var(--accent); }
.perf-card .value.yellow { color: var(--yellow); }

/* ===== 时间轴 ===== */
.timeline {
    display: flex;
    align-items: center;
    gap: 2px;
    margin-bottom: 16px;
    padding: 6px 0;
    overflow-x: auto;
}
.timeline-bar {
    height: 20px;
    border-radius: 3px;
    cursor: pointer;
    transition: filter 0.15s;
    min-width: 4px;
}
.timeline-bar:hover { filter: brightness(1.4); }
.timeline-bar.llm { background: var(--accent); }
.timeline-bar.tool { background: var(--green); }
.timeline-legend {
    display: flex;
    gap: 16px;
    margin-bottom: 12px;
    font-size: 0.78rem;
    color: var(--muted);
}
.timeline-legend span { display: flex; align-items: center; gap: 5px; }
.timeline-legend .dot { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.timeline-legend .dot.llm { background: var(--accent); }
.timeline-legend .dot.tool { background: var(--green); }

/* ===== Trace 卡片 ===== */
.trace {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 20px;
    overflow: hidden;
}
.trace-header {
    padding: 12px 16px;
    background: rgba(88,166,255,0.06);
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    user-select: none;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
}
.trace-header:hover { background: rgba(88,166,255,0.12); }
.trace-header h2 { font-size: 0.95rem; color: var(--accent); display: flex; align-items: center; gap: 8px; flex: 1; min-width: 200px; }
.trace-header .arrow { transition: transform 0.2s; font-size: 0.8rem; display: inline-block; }
.trace-header.open .arrow { transform: rotate(90deg); }
.trace-header .badge {
    font-size: 0.75rem;
    padding: 2px 8px;
    border-radius: 12px;
    background: rgba(88,166,255,0.15);
    color: var(--accent);
    white-space: nowrap;
}
.trace-body { display: none; padding: 16px; }
.trace-body.open { display: block; }

.question {
    background: rgba(63,185,80,0.08);
    border-left: 3px solid var(--green);
    padding: 8px 12px;
    margin-bottom: 14px;
    border-radius: 0 4px 4px 0;
    font-size: 0.93rem;
}

/* ===== 步骤卡片 ===== */
.step {
    margin-bottom: 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
}
.step-header {
    padding: 8px 14px;
    background: rgba(210,153,29,0.06);
    border-bottom: 1px solid var(--border);
    font-weight: 600;
    color: var(--yellow);
    font-size: 0.85rem;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}
.step-header .step-timing {
    font-weight: 400;
    font-size: 0.78rem;
    color: var(--muted);
    margin-left: auto;
}
.step-header .step-timing span { margin-left: 10px; }
.step-header .step-timing .llm-time { color: var(--accent); }
.step-header .step-timing .tool-time { color: var(--green); }
.step-body { padding: 12px; }
.field { margin-bottom: 10px; }
.field-label {
    font-size: 0.72rem;
    color: var(--muted);
    text-transform: uppercase;
    margin-bottom: 4px;
    font-weight: 600;
    letter-spacing: 0.5px;
}
.field-content {
    background: var(--bg);
    padding: 10px;
    border-radius: 4px;
    font-family: "Fira Code", "Cascadia Code", "JetBrains Mono", monospace;
    font-size: 0.83rem;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 350px;
    overflow-y: auto;
    border: 1px solid var(--border);
}
.action { color: var(--orange); }
.observation { color: var(--green); }
.final-answer {
    color: var(--green);
    font-weight: 600;
    font-size: 1.02rem;
    padding: 12px;
    background: rgba(63,185,80,0.06);
    border-radius: 4px;
    border-left: 3px solid var(--green);
    margin-top: 12px;
}
.empty { text-align: center; color: var(--muted); padding: 60px; font-size: 1.1rem; }
.meta { color: var(--muted); font-size: 0.78rem; margin-top: 4px; }
.raw-toggle {
    font-size: 0.78rem;
    color: var(--muted);
    cursor: pointer;
    user-select: none;
    margin-bottom: 8px;
}
.raw-toggle:hover { color: var(--text); }
.raw-content { display: none; margin-bottom: 10px; }
.raw-content.open { display: block; }

/* ===== 性能条形图（步骤内联） ===== */
.perf-bar-wrap {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 10px;
    font-size: 0.73rem;
    color: var(--muted);
}
.perf-bar {
    height: 5px;
    border-radius: 3px;
    transition: width 0.3s;
    min-width: 2px;
}
.perf-bar.llm-bar { background: var(--accent); }
.perf-bar.tool-bar { background: var(--green); }
</style>
</head>
<body>
<h1>🔍 ReAct Trace Viewer</h1>
<p class="summary" id="summary"></p>
<div id="container"></div>
<script>
const traces = __DATA_PLACEHOLDER__;
const container = document.getElementById('container');

// 全局统计摘要
const totalRuns = traces.length;
const totalSteps = traces.reduce(function(s, t) { return s + (t.total_steps || (t.steps ? t.steps.length : 0)); }, 0);
const avgSteps = totalRuns > 0 ? (totalSteps / totalRuns).toFixed(1) : 0;
const avgTime = totalRuns > 0
    ? (traces.reduce(function(s, t) { return s + (t.total_ms || 0); }, 0) / totalRuns / 1000).toFixed(1)
    : 0;

document.getElementById('summary').innerHTML =
    '共 <strong>' + totalRuns + '</strong> 条 trace &middot; 总 <strong>' + totalSteps + '</strong> 步 &middot; 平均 <strong>' + avgSteps + '</strong> 步/次 &middot; 平均耗时 <strong>' + avgTime + 's</strong> &middot; 数据源：data/react_traces.jsonl';

if (traces.length === 0) {
    container.innerHTML = '<div class="empty">暂无 trace 记录。<br>运行 python -m src.agent_raw.main "你的问题" 后刷新此页面。</div>';
} else {
    traces.forEach(function(trace, idx) {
        var steps = trace.steps || [];

        // 计算性能摘要
        var totalMs = trace.total_ms || 0;
        var totalStepsCount = trace.total_steps || steps.length;
        var avgMs = totalStepsCount > 0 ? totalMs / totalStepsCount : 0;
        var totalLlmMs = steps.reduce(function(s, st) { return s + (st.llm_ms || 0); }, 0);
        var totalToolMs = steps.reduce(function(s, st) { return s + (st.tool_ms || 0); }, 0);

        var traceEl = document.createElement('div');
        traceEl.className = 'trace';

        // Header
        var header = document.createElement('div');
        header.className = 'trace-header';
        header.innerHTML = '<h2><span class="arrow">▶</span> #' + (idx + 1) + '：' + escapeHtml(trace.question) + '</h2>' +
            '<span class="badge">' + totalStepsCount + ' 步 &middot; ' + (totalMs/1000).toFixed(1) + 's</span>' +
            '<div class="meta" style="margin-left:12px">' + (trace.started_at || '') + ' &middot; model: ' + (trace.model || '?') + '</div>';
        var body = document.createElement('div');
        body.className = 'trace-body';
        header.onclick = function() {
            header.classList.toggle('open');
            body.classList.toggle('open');
        };
        traceEl.appendChild(header);

        // 性能摘要卡片
        body.innerHTML += '<div class="perf-summary">' +
            '<div class="perf-card"><div class="label">总耗时</div><div class="value accent">' + (totalMs/1000).toFixed(1) + 's</div></div>' +
            '<div class="perf-card"><div class="label">总步数</div><div class="value">' + totalStepsCount + '</div></div>' +
            '<div class="perf-card"><div class="label">平均/步</div><div class="value yellow">' + (avgMs/1000).toFixed(1) + 's</div></div>' +
            '<div class="perf-card"><div class="label">LLM 合计</div><div class="value accent">' + (totalLlmMs/1000).toFixed(1) + 's</div></div>' +
            '<div class="perf-card"><div class="label">工具合计</div><div class="value green">' + (totalToolMs/1000).toFixed(1) + 's</div></div>' +
        '</div>';

        // 时间轴条形图
        if (steps.length > 0) {
            var maxMs = Math.max.apply(null, steps.map(function(s) { return (s.llm_ms||0) + (s.tool_ms||0); })) || 1;
            body.innerHTML += '<div class="timeline-legend"><span><span class="dot llm"></span> LLM 调用</span><span><span class="dot tool"></span> 工具执行</span></div>';
            body.innerHTML += '<div class="timeline">';
            steps.forEach(function(step, si) {
                var llmW = Math.max(((step.llm_ms||0) / maxMs) * 100, 3);
                var toolW = step.tool_ms ? Math.max(((step.tool_ms||0) / maxMs) * 100, 3) : 0;
                body.innerHTML +=
                    '<div class="timeline-bar llm" style="width:' + llmW + 'px" title="Step ' + (si+1) + ' LLM: ' + (step.llm_ms||0).toFixed(0) + 'ms"></div>';
                if (toolW > 0) {
                    body.innerHTML +=
                        '<div class="timeline-bar tool" style="width:' + toolW + 'px" title="Step ' + (si+1) + ' Tool: ' + (step.tool_ms||0).toFixed(0) + 'ms"></div>';
                }
            });
            body.innerHTML += '</div>';
        }

        // Question
        body.innerHTML += '<div class="question"><strong>📝 Question:</strong> ' + escapeHtml(trace.question) + '</div>';

        // Steps
        steps.forEach(function(step) {
            var llmMs = step.llm_ms || 0;
            var toolMs = step.tool_ms || 0;
            var stepTotalMs = step.total_ms || 0;

            var stepHtml = '<div class="step">' +
                '<div class="step-header">' +
                    'Step ' + step.step +
                    '<span class="step-timing">' +
                        (llmMs ? '<span class="llm-time">🤖 LLM ' + (llmMs/1000).toFixed(2) + 's</span>' : '') +
                        (toolMs ? '<span class="tool-time">🔧 工具 ' + (toolMs/1000).toFixed(2) + 's</span>' : '') +
                        (stepTotalMs ? '<span>⏱ 累计 ' + (stepTotalMs/1000).toFixed(1) + 's</span>' : '') +
                    '</span>' +
                '</div>' +
                '<div class="step-body">';

            // 内联性能条形图
            var maxStepMs = Math.max(llmMs, toolMs, 1);
            stepHtml += '<div class="perf-bar-wrap">' +
                '🤖 LLM <div class="perf-bar llm-bar" style="width:' + Math.max((llmMs/maxStepMs)*120, 2) + 'px"></div> ' + (llmMs/1000).toFixed(2) + 's';
            if (toolMs) {
                stepHtml += ' &nbsp;🔧 Tool <div class="perf-bar tool-bar" style="width:' + Math.max((toolMs/maxStepMs)*120, 2) + 'px"></div> ' + (toolMs/1000).toFixed(2) + 's';
            }
            stepHtml += '</div>';

            stepHtml += '<div class="field"><div class="field-label">💭 Thought</div><div class="field-content">' + escapeHtml(step.thought || '') + '</div></div>';
            if (step.action) {
                stepHtml += '<div class="field"><div class="field-label">🔧 Action</div><div class="field-content action">' + escapeHtml(step.action) + '</div></div>' +
                    '<div class="field"><div class="field-label">📥 Action Input</div><div class="field-content">' + escapeHtml(step.action_input || '') + '</div></div>';
            }
            if (step.observation) {
                stepHtml += '<div class="field"><div class="field-label">📤 Observation</div><div class="field-content observation">' + escapeHtml(step.observation) + '</div></div>';
            }
            if (step.final_answer) {
                stepHtml += '<div class="final-answer">✅ Final Answer: ' + escapeHtml(step.final_answer) + '</div>';
            }
            // Raw prompt toggle
            if (step.prompt) {
                stepHtml += '<div class="raw-toggle" onclick="var n=this.nextElementSibling;n.classList.toggle(\'open\');this.textContent=n.classList.contains(\'open\')?\'▼ 收起原始 Prompt\':\'▶ 查看原始 Prompt\'">▶ 查看原始 Prompt</div>' +
                    '<div class="raw-content"><div class="field"><div class="field-label">Prompt (sent to LLM)</div><div class="field-content">' + escapeHtml(step.prompt) + '</div></div></div>';
            }
            if (step.raw_output) {
                stepHtml += '<div class="raw-toggle" onclick="var n=this.nextElementSibling;n.classList.toggle(\'open\');this.textContent=n.classList.contains(\'open\')?\'▼ 收起原始输出\':\'▶ 查看原始 LLM 输出\'">▶ 查看原始 LLM 输出</div>' +
                    '<div class="raw-content"><div class="field"><div class="field-label">Raw LLM Output</div><div class="field-content">' + escapeHtml(step.raw_output) + '</div></div></div>';
            }
            stepHtml += '</div></div>';
            body.innerHTML += stepHtml;
        });

        // Final Answer
        if (trace.final_answer) {
            body.innerHTML += '<div class="final-answer">🎯 最终答案：' + escapeHtml(trace.final_answer) + '</div>';
        }

        traceEl.appendChild(body);
        container.appendChild(traceEl);
    });

    // Auto-expand first trace
    var firstHeader = container.querySelector('.trace-header');
    var firstBody = container.querySelector('.trace-body');
    if (firstHeader && firstBody) {
        firstHeader.classList.add('open');
        firstBody.classList.add('open');
    }
}

function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
</script>
</body>
</html>"""


def generate_html(traces: list) -> str:
    """生成带交互展示和性能分析的 HTML 字符串。"""
    data_json = json.dumps(traces, ensure_ascii=False, indent=2)
    return HTML_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json)


def main():
    traces = load_traces()
    html = generate_html(traces)
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"✅ 已生成 {HTML_PATH}（共 {len(traces)} 条 trace）")
    print(f"🌐 浏览器打开：file://{HTML_PATH}")


if __name__ == "__main__":
    main()
