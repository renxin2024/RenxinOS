#!/usr/bin/env python3
"""
run_hybrid_eval.py — Hybrid 检索评测脚本
使用 retrieve_hybrid() 评测，与 keyword 基线和 embedding 结果对比
"""
import sys, os
sys.path.insert(0, '/Users/renxin/ai_brain/RenxinOS')
os.chdir('/Users/renxin/ai_brain/RenxinOS')
import json
from collections import defaultdict

from src.embedding import load_embeddings
load_embeddings()

from src.agent import retrieve_hybrid

with open('data/eval_questions.json', encoding='utf-8') as f:
    questions = json.load(f)

TOP_K = 8
results = []

for q in questions:
    hits = retrieve_hybrid(q['question'], top_k=TOP_K)
    retrieved_files = [h['file'] for h in hits]
    expected = set(q['expected_source_files'])

    if q['type'] == 'unanswerable':
        recall = 1.0 if len(hits) == 0 else 0.0
        top_score = hits[0].get('score', 0) if hits else 0
        failure = 'SHOULD_REFUSE' if len(hits) > 0 and top_score > 0.5 else 'NONE'
    else:
        recalled = expected & set(retrieved_files)
        recall = len(recalled) / len(expected) if expected else 0.0
        failure = 'SEARCH_FAILURE' if not recalled else 'NONE'

    top_content = ' '.join(h.get('content', '') for h in hits).lower()
    kw_hits = sum(1 for kw in q['expected_answer_keywords'] if kw.lower() in top_content)
    kw_total = len(q['expected_answer_keywords'])
    kw_score = kw_hits / kw_total if kw_total > 0 else 0.0

    if failure == 'NONE' and q['type'] != 'unanswerable' and kw_score < 0.5:
        failure = 'CONTEXT_INCOMPLETE'

    results.append({
        'id': q['id'], 'question': q['question'], 'type': q['type'],
        'recall': recall, 'kw_score': kw_score,
        'failure': failure,
        'retrieved_files': retrieved_files[:3],
        'expected_files': list(expected),
    })

print()
print('=== Hybrid 检索评测 ===')
print()
hdr = '{:>3} | {:>13} | {:>7} | {:>7} | {:>22} | {}'.format('ID','Type','Recall','KW','Failure','Question')
print(hdr)
print('-' * 100)
for r in results:
    print('{:>3} | {:>13} | {:>7.1%} | {:>7.1%} | {:>22} | {}'.format(
        r['id'], r['type'], r['recall'], r['kw_score'], r['failure'], r['question']))

print()
avg_recall = sum(r['recall'] for r in results) / len(results)
avg_kw = sum(r['kw_score'] for r in results) / len(results)
print('=== Summary ===')
print('Total questions:   {}'.format(len(results)))
print('Average Recall@{}: {:.1%}'.format(TOP_K, avg_recall))
print('Average KW Score:  {:.1%}'.format(avg_kw))

print()
print('=== By Type ===')
by_type = defaultdict(list)
for r in results:
    by_type[r['type']].append(r)
for t, items in sorted(by_type.items()):
    tr = sum(r['recall'] for r in items)/len(items)
    tk = sum(r['kw_score'] for r in items)/len(items)
    print('  {:>13}: recall={:.1%}  kw={:.1%}  (n={})'.format(t, tr, tk, len(items)))

print()
print('=== Failure Modes ===')
fc = defaultdict(int)
for r in results:
    fc[r['failure']] += 1
for mode, count in sorted(fc.items(), key=lambda x: -x[1]):
    print('  {:>22}: {:>2} ({:.0%})'.format(mode, count, count/len(results)))

print()
print('=== Paraphrase Consistency ===')
pgroups = defaultdict(list)
for r in results:
    q = next(qq for qq in questions if qq['id'] == r['id'])
    if q['type'] == 'paraphrase':
        g = q.get('paraphrase_group', '')
        if g:
            pgroups[g].append(r)
for group, items in pgroups.items():
    recalls = [r['recall'] for r in items]
    ok = len(set(recalls)) == 1
    print('  group "{}": {} recalls={} {}'.format(
        group, '->'.join(str(r['id']) for r in items),
        ['{:.0%}'.format(r) for r in recalls],
        'PASS consistent' if ok else 'WARN INCONSISTENT'))

print()
print('=== 三路对比 ===')
print('  Keyword:   Recall@8=61.5%  KW=71.3%  SEARCH_FAILURE=3  SHOULD_REFUSE=2  CONTEXT_INCOMPLETE=2')
print('  Embedding: Recall@8=84.4%  KW=82.5%  SEARCH_FAILURE=0  SHOULD_REFUSE=1  CONTEXT_INCOMPLETE=0')
print('  Hybrid:    Recall@8={:.1%}  KW={:.1%}  failures above'.format(avg_recall, avg_kw))
