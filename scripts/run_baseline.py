# ============================================================
# run_baseline.py — RAG 评测脚本（keyword 基线）
# 功能：加载评测题 → 跑 keyword 检索 → 输出诊断报告
# ============================================================

# --- 导入模块 ---
# sys: 系统相关，这里用来修改 Python 模块搜索路径
# os: 操作系统相关，这里用来切换工作目录
import sys, os

# sys.path 是一个 list，存放 Python 查找模块的目录列表
# insert(0, path) 把 RenxinOS 目录插到最前面，这样 import src.agent 才能找到
# 类比 Java: 相当于在 classpath 中添加一个路径
sys.path.insert(0, '/Users/renxin/ai_brain/RenxinOS')

# chdir = change directory，切换当前工作目录
# 这样下面用相对路径 'data/eval_questions.json' 就能找到文件
os.chdir('/Users/renxin/ai_brain/RenxinOS')

# json: Python 内置的 JSON 处理模块（标准库自带，不需要 pip install）
import json

# defaultdict: 一种特殊的 dict，访问不存在的 key 时自动用默认值初始化
# 类比 Java: 相当于 new HashMap<K, V>() 但 get 时自动 put 默认值
# defaultdict(list) -> 不存在的 key 自动创建空 list
# defaultdict(int)  -> 不存在的 key 自动创建 0
from collections import defaultdict

# 从我们自己写的 agent 模块导入两个函数
# retrieve: 根据查询文本检索相关文档片段
# load_chunks: 预加载所有文档 chunk 到内存
from src.agent import retrieve, load_chunks

# 预加载文档 chunk（首次运行会解析所有笔记文件）
load_chunks()

# --- 加载评测题 ---
# with open(...) as f: Python 的上下文管理器（类似 Java 的 try-with-resources）
# 作用：文件使用完毕后自动关闭，即使发生异常也会关闭
# encoding='utf-8': 指定文件编码，中文文件必须指定
with open('data/eval_questions.json', encoding='utf-8') as f:
    # json.load(f): 从文件对象读取 JSON 并解析为 Python 对象
    # 结果是一个 list，每个元素是一个 dict（对应一道评测题）
    questions = json.load(f)

# --- 配置常量 ---
# TOP_K: 检索返回的文档数量（类比 SQL 的 LIMIT）
TOP_K = 8
# results: 存放每道题的评测结果（类似 Java 的 ArrayList<Result>）
results = []

# --- 逐题评测 ---
# for q in questions: 遍历 list 中的每个元素（类似 Java 的 for-each）
for q in questions:
    # 调用检索函数，返回 top_k 个最相关的文档片段
    # 每个 hit 是一个 dict: {'file': '文件名', 'content': '内容', 'score': 分数}
    hits = retrieve(q['question'], top_k=TOP_K)

    # 列表推导式（List Comprehension）—— Python 最有特色的语法之一
    # [h['file'] for h in hits] 等价于 Java:
    #   List<String> files = new ArrayList<>();
    #   for (Hit h : hits) { files.add(h.get("file")); }
    retrieved_files = [h['file'] for h in hits]

    # set(): 将 list 转为集合（类似 Java 的 HashSet）
    # 用于后续的集合交集运算（& 操作符）
    expected = set(q['expected_source_files'])

    # --- 检索诊断：判断检索是否正确 ---
    if q['type'] == 'unanswerable':
        # 负例题：知识库中不应有答案
        # 三元表达式（类似 Java 的 条件 ? 值A : 值B）
        # 如果 hits 为空 -> recall=1.0（正确没返回）；否则 -> 0.0（错误返回了）
        recall = 1.0 if len(hits) == 0 else 0.0
        # .get('score', 0): 安全获取 dict 的值，key 不存在时返回默认值 0
        # 类比 Java: map.getOrDefault("score", 0)
        # 如果有返回结果且分数 > 0.3 -> 应该拒答但没拒 -> SHOULD_REFUSE
        failure = 'SHOULD_REFUSE' if len(hits) > 0 and hits[0].get('score', 0) > 0.3 else 'NONE'
    else:
        # 正常题：检查期望文件是否被检索到
        # expected & set(retrieved_files): 集合交集运算（类似 Java: set1.retainAll(set2)）
        # 结果 = 既在期望列表中又被检索到的文件
        recalled = expected & set(retrieved_files)
        # recall = 召回的文件数 / 期望文件总数
        # if expected: Python 中空集合/空列表/0/None 都视为 False（truthy/falsy 特性）
        recall = len(recalled) / len(expected) if expected else 0.0
        # not recalled: 如果交集为空（没召回任何期望文件）-> 检索失败
        if not recalled:
            failure = 'SEARCH_FAILURE'
        else:
            failure = 'NONE'

    # --- 内容诊断：检查检索到的内容是否包含答案关键词 ---
    # ' '.join(...): 用空格把多个字符串拼接成一个（类似 Java 的 String.join）
    # h.get('content', ''): 安全获取内容，没有则返回空字符串
    # .lower(): 转为小写（类似 Java 的 .toLowerCase()）
    # 注意: (h.get(...) for h in hits) 是生成器表达式，惰性求值，比列表推导式省内存
    top_content = ' '.join(h.get('content', '') for h in hits).lower()

    # sum(1 for kw in ... if ...): 生成器表达式 + sum
    # 遍历所有关键词，如果在 top_content 中出现就计 1，最后求和
    # 类比 Java: keywords.stream().filter(kw -> content.contains(kw)).count()
    kw_hits = sum(1 for kw in q['expected_answer_keywords'] if kw.lower() in top_content)
    kw_total = len(q['expected_answer_keywords'])
    # 关键词得分 = 命中数 / 总关键词数
    kw_score = kw_hits / kw_total if kw_total > 0 else 0.0

    # 如果检索到了文件但内容不包含足够关键词 -> 上下文不完整
    if failure == 'NONE' and q['type'] != 'unanswerable' and kw_score < 0.5:
        failure = 'CONTEXT_INCOMPLETE'

    # 将本题结果追加到 results 列表
    # Python dict 用花括号创建，key-value 用冒号分隔（类似 Java Map.of(...)）
    results.append({
        'id': q['id'],                                    # 题号
        'question': q['question'],                        # 题目文本
        'type': q['type'],                                # 题目类型
        'recall': recall,                                 # 召回率
        'kw_score': kw_score,                             # 关键词得分
        'kw_hits': kw_hits,                               # 命中关键词数
        'kw_total': kw_total,                             # 总关键词数
        'failure': failure,                               # 失败模式
        'retrieved_files': retrieved_files[:3],           # 前 3 个检索结果
        # [:3] 是切片语法（Slice），取 list 的前 3 个元素，类似 Java 的 subList(0, 3)
        'expected_files': list(expected),                 # 期望文件列表
        # list(set): 把集合转回列表（类似 Java: new ArrayList<>(set)）
        'recalled_files': list(expected & set(retrieved_files)) if expected else [],
        # hits[0]['score'] if hits else 0.0: 安全获取最高分，列表为空时返回 0
        # 类比 Java: hits.isEmpty() ? 0.0 : hits.get(0).getScore()
        'top_score': hits[0]['score'] if hits else 0.0,  # 最高分
        'num_hits': len(hits),                            # 返回结果数
    })

# ========== 输出报告 ==========

# --- 逐题明细 ---
print()
# '{:>3}': 格式化字符串，> 表示右对齐，3 表示最小宽度
# .format() 方法类似 Java 的 String.format()，但语法不同
# {:.1%} 表示百分比格式，保留 1 位小数（0.883 -> "88.3%"）
hdr = '{:>3} | {:>13} | {:>7} | {:>7} | {:>22} | {}'.format(
    'ID', 'Type', 'Recall', 'KW', 'Failure', 'Question')
print(hdr)
# '-' * 100: 字符串重复 100 次（类似 Java: "-".repeat(100)）
print('-' * 100)
for r in results:
    line = '{:>3} | {:>13} | {:>7.1%} | {:>7.1%} | {:>22} | {}'.format(
        r['id'], r['type'], r['recall'], r['kw_score'], r['failure'], r['question'])
    print(line)

# --- 汇总统计 ---
print()
print('=== Summary ===')
# sum(r[...] for r in results): 生成器表达式求和
# 类比 Java: results.stream().mapToDouble(r -> r.getRecall()).sum()
avg_recall = sum(r['recall'] for r in results) / len(results)
avg_kw = sum(r['kw_score'] for r in results) / len(results)
print('Total questions:        {}'.format(len(results)))
print('Average Recall@{}:      {:.1%}'.format(TOP_K, avg_recall))
print('Average KW Score:       {:.1%}'.format(avg_kw))

# --- 按题型分组统计 ---
print()
print('=== By Type ===')
# defaultdict(list): 自动按 type 分组（类似 Java 的 Collectors.groupingBy）
by_type = defaultdict(list)
for r in results:
    by_type[r['type']].append(r)  # 按 type 追加到对应列表

# sorted(by_type.items()): dict.items() 返回 (key, value) 对的列表
# 类比 Java: map.entrySet().stream().sorted()
# t, items: 元组解包（Tuple Unpacking），一次赋值多个变量
for t, items in sorted(by_type.items()):
    tr = sum(r['recall'] for r in items) / len(items)
    tk = sum(r['kw_score'] for r in items) / len(items)
    print('  {:>13}: recall={:.1%}  kw={:.1%}  (n={})'.format(t, tr, tk, len(items)))

# --- 失败模式统计 ---
print()
print('=== Failure Modes ===')
# defaultdict(int): 不存在的 key 自动初始化为 0（类似计数器）
failure_counts = defaultdict(int)
for r in results:
    failure_counts[r['failure']] += 1

# sorted(..., key=lambda x: -x[1]): 按第二个元素（count）降序排列
# lambda x: -x[1] 是匿名函数，x 是 (mode, count) 元组，-x[1] 取负实现降序
# 类比 Java: Comparator.comparingInt(e -> -e.getValue())
for mode, count in sorted(failure_counts.items(), key=lambda x: -x[1]):
    pct = count / len(results)
    print('  {:>22}: {:>2} ({:.0%})'.format(mode, count, pct))

# --- 同义改写一致性检查 ---
# defaultdict(list): 按 paraphrase_group 分组
paraphrase_groups = defaultdict(list)
for r in results:
    # next(qq for qq in questions if ...): 找到第一个匹配的评测题
    # 类比 Java: questions.stream().filter(...).findFirst().get()
    q = next(qq for qq in questions if qq['id'] == r['id'])
    if q['type'] == 'paraphrase':
        # .get('paraphrase_group', ''): 获取分组名，不存在则返回空字符串
        group = q.get('paraphrase_group', '')
        if group:  # 非空字符串才处理（Python: 空字符串是 falsy）
            paraphrase_groups[group].append(r)

if paraphrase_groups:  # 如果有改写组
    print()
    print('=== Paraphrase Consistency ===')
    # .items(): 遍历 dict 的所有 key-value 对
    for group, items in paraphrase_groups.items():
        # 提取该组所有 recall 值
        recalls = [r['recall'] for r in items]
        # set(recalls): 转为集合去重。如果所有值相同 -> 集合大小=1 -> 一致
        consistent = len(set(recalls)) == 1
        status = 'PASS consistent' if consistent else 'WARN INCONSISTENT'
        print('  group "{}": {} recalls={} {}'.format(
            group, '->'.join(str(r['id']) for r in items),
            ['{:.0%}'.format(r) for r in recalls], status))

# --- 失败详情 ---
# 列表推导式筛选出所有失败的结果
# [r for r in results if ...] 类比 Java: results.stream().filter(...).collect(toList())
failures = [r for r in results if r['failure'] != 'NONE']
if failures:
    print()
    print('=== Failure Details ===')
    for r in failures:
        print()
        print('  Q{} [{}] {}'.format(r['id'], r['type'], r['question']))
        print('    failure: {}'.format(r['failure']))
        # {:.3f}: 浮点数保留 3 位小数
        print('    top_score: {:.3f}  num_hits: {}'.format(r['top_score'], r['num_hits']))
        print('    retrieved: {}'.format(r['retrieved_files']))
        if r['expected_files']:  # 如果期望文件列表非空（非空列表是 truthy）
            print('    expected:  {}'.format(r['expected_files']))
            print('    recalled:  {}'.format(r['recalled_files']))
        print('    kw: {}/{}'.format(r['kw_hits'], r['kw_total']))

