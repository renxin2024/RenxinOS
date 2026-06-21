#!/usr/bin/env python3
"""
run_embedding_eval.py — Embedding 语义检索评测脚本
与 run_baseline.py 相同的评测逻辑，但使用 retrieve_semantic 替代 retrieve
用于对比 keyword 基线和 embedding 检索的效果差异
"""
import sys, os
sys.path.insert(0, '/Users/renxin/ai_brain/RenxinOS')
os.chdir('/Users/renxin/ai_brain/RenxinOS')
import json
from collections import defaultdict

# 导入语义检索函数（替代 keyword 的 retrieve）
from src.embedding import retrieve_semantic, load_embeddings

# 预加载 embedding 数据（避免每次查询都重新加载）
load_embeddings()

with open('data/eval_questions.json', encoding='utf-8') as f:
    questions = json.load(f)

TOP_K = 8
results = []

for q in questions:
    # 唯一区别：这里用 retrieve_semantic 替代 retrieve
    hits = retrieve_semantic(q['question'], top_k=TOP_K)
    retrieved_files = [h['file'] for h in hits]
    expected = set(q['expected_source_files'])

    if q['type'] == 'unanswerable':
        recall = 1.0 if len(hits) == 0 else 0.0
        # Embedding 的 score 范围不同（0-1），阈值也要调
        # cosine similarity > 0.5 说明语义比较接近
        failure = 'SHOULD_REFUSE' if len(hits) > 0 and hits[0].get('score', 0) > 0.5 else 'NONE'
    else:
        recalled = expected & set(retrieved_files)
        recall = len(recalled) / len(expected) if expected else 0.0
        if not recalled:
            failure = 'SEARCH_FAILURE'
        else:
            failure = 'NONE'

    top_content = ' '.join(h.get('content', '') for h in hits).lower()
    kw_hits = sum(1 for kw in q['expected_answer_keywords'] if kw.lower() in top_content)
    kw_total = len(q['expected_answer_keywords'])
    kw_score = kw_hits / kw_total if kw_total > 0 else 0.0

    if failure == 'NONE' and q['type'] != 'unanswerable' and kw_score < 0.5:
        failure = 'CONTEXT_INCOMPLETE'

    results.append({
        'id': q['id'], 'question': q['question'], 'type': q['type'],
        'recall': recall, 'kw_score': kw_score,
        'kw_hits': kw_hits, 'kw_total': kw_total,
        'failure': failure,
        'retrieved_files': retrieved_files[:3],
        'expected_files': list(expected),
        'recalled_files': list(expected & set(retrieved_files)) if expected else [],
        'top_score': hits[0]['score'] if hits else 0.0,
        'num_hits': len(hits),
    })

# ========== 输出 ==========
print()
print('=== Embedding 语义检索评测 ===')
print()
hdr = '{:>3} | {:>13} | {:>7} | {:>7} | {:>22} | {}'.format(
    'ID', 'Type', 'Recall', 'KW', 'Failure', 'Question')
print(hdr)
print('-' * 100)
for r in results:
    line = '{:>3} | {:>13} | {:>7.1%} | {:>7.1%} | {:>22} | {}'.format(
        r['id'], r['type'], r['recall'], r['kw_score'], r['failure'], r['question'])
    print(line)

print()
print('=== Summary ===')
avg_recall = sum(r['recall'] for r in results) / len(results)
avg_kw = sum(r['kw_score'] for r in results) / len(results)
print('Total questions:        {}'.format(len(results)))
print('Average Recall@{}:      {:.1%}'.format(TOP_K, avg_recall))
print('Average KW Score:       {:.1%}'.format(avg_kw))

print()
print('=== By Type ===')
by_type = defaultdict(list)
for r in results:
    by_type[r['type']].append(r)
for t, items in sorted(by_type.items()):
    tr = sum(r['recall'] for r in items) / len(items)
    tk = sum(r['kw_score'] for r in items) / len(items)
    print('  {:>13}: recall={:.1%}  kw={:.1%}  (n={})'.format(t, tr, tk, len(items)))

print()
print('=== Failure Modes ===')
failure_counts = defaultdict(int)
for r in results:
    failure_counts[r['failure']] += 1
for mode, count in sorted(failure_counts.items(), key=lambda x: -x[1]):
    pct = count / len(results)
    print('  {:>22}: {:>2} ({:.0%})'.format(mode, count, pct))

paraphrase_groups = defaultdict(list)
for r in results:
    q = next(qq for qq in questions if qq['id'] == r['id'])
    if q['type'] == 'paraphrase':
        group = q.get('paraphrase_group', '')
        if group:
            paraphrase_groups[group].append(r)
if paraphrase_groups:
    print()
    print('=== Paraphrase Consistency ===')
    for group, items in paraphrase_groups.items():
        recalls = [r['recall'] for r in items]
        consistent = len(set(recalls)) == 1
        status = 'PASS consistent' if consistent else 'WARN INCONSISTENT'
        print('  group "{}": {} recalls={} {}'.format(
            group, '->'.join(str(r['id']) for r in items),
            ['{:.0%}'.format(r) for r in recalls], status))

# ========== 对比 Keyword 基线 ==========
print()
print('=== vs Keyword Baseline ===')
print('  Keyword:  Recall@8 = 61.5%  |  KW = 71.3%  |  SEARCH_FAILURE=3  SHOULD_REFUSE=2')
print('  Embedding: Recall@8 = {:.1%}  |  KW = {:.1%}  |  failures above'.format(avg_recall, avg_kw))
