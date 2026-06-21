"""
eval_sanity_check.py — 评测集上线前必跑的三项健全性检查

用法：
    python scripts/eval_sanity_check.py

三项检查：
    1. expected_source_files 是否在知识库（chunks.json）中
    2. expected_answer_keywords 是否真实存在于期望文件的内容中
    3. ground_truth_answer 是否涵盖了所有 expected_answer_keywords
"""

import sys
import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

CHUNKS_PATH = "data/chunks.json"
EVAL_PATH = "data/eval_questions.json"


def load_data():
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        chunks = json.load(f)
    with open(EVAL_PATH, encoding="utf-8") as f:
        questions = json.load(f)
    file_content = {}
    for c in chunks:
        fname = c["file"]
        file_content[fname] = file_content.get(fname, "") + "\n" + c.get("content", "")
    all_files = set(file_content.keys())
    return questions, file_content, all_files


def check1_source_files_in_kb(questions, all_files):
    """检查1：expected_source_files 是否在知识库中"""
    errors = []
    for q in questions:
        for f in q["expected_source_files"]:
            if f not in all_files:
                errors.append("Q{}: 期望文件不在知识库: {}".format(q["id"], f))
    return errors


def check2_keywords_in_source(questions, file_content):
    """检查2：expected_answer_keywords 是否真实存在于期望文件内容中"""
    errors = []
    for q in questions:
        if q["type"] == "unanswerable":
            continue
        src = " ".join(file_content.get(f, "") for f in q["expected_source_files"])
        for kw in q["expected_answer_keywords"]:
            if kw.lower() not in src.lower():
                errors.append(
                    "Q{} [{}]: 关键词「{}」在期望文件中找不到 (文件: {})".format(
                        q["id"], q["type"], kw, q["expected_source_files"]
                    )
                )
    return errors


def check3_gt_covers_keywords(questions, file_content):
    """检查3：ground_truth_answer 是否涵盖了所有 expected_answer_keywords"""
    errors = []
    for q in questions:
        if q["type"] == "unanswerable":
            continue
        gta = q.get("ground_truth_answer", "")
        src = " ".join(file_content.get(f, "") for f in q["expected_source_files"])
        for kw in q["expected_answer_keywords"]:
            if kw.lower() in src.lower() and kw.lower() not in gta.lower():
                errors.append(
                    "Q{} [{}]: ground_truth 缺少关键词「{}」(笔记中存在)".format(
                        q["id"], q["type"], kw
                    )
                )
    return errors


def main():
    print("=" * 60)
    print("评测集 Sanity Check")
    print("=" * 60)

    questions, file_content, all_files = load_data()
    total_questions = len(questions)
    answerable = [q for q in questions if q["type"] != "unanswerable"]

    print("\n加载完成：{} 道题，{} 个知识库文件\n".format(total_questions, len(all_files)))

    all_passed = True

    print("【检查1】expected_source_files 是否在知识库中")
    errors1 = check1_source_files_in_kb(questions, all_files)
    if errors1:
        all_passed = False
        for e in errors1:
            print("  ❌ " + e)
    else:
        print("  ✅ 全部 {} 道题的期望文件均在知识库中".format(total_questions))

    print("\n【检查2】expected_answer_keywords 是否真实存在于期望文件内容中")
    errors2 = check2_keywords_in_source(questions, file_content)
    if errors2:
        all_passed = False
        for e in errors2:
            print("  ❌ " + e)
    else:
        print("  ✅ 全部 {} 道可答题的关键词覆盖正常".format(len(answerable)))

    print("\n【检查3】ground_truth_answer 是否涵盖了所有 expected_answer_keywords")
    errors3 = check3_gt_covers_keywords(questions, file_content)
    if errors3:
        all_passed = False
        for e in errors3:
            print("  ❌ " + e)
    else:
        print("  ✅ 全部 {} 道可答题的 ground_truth 与关键词对齐正常".format(len(answerable)))

    print("\n" + "=" * 60)
    total_errors = len(errors1) + len(errors2) + len(errors3)
    if all_passed:
        print("✅ 全部通过（0 个问题），评测集质量合格，可以上线。")
    else:
        print("⚠️  发现 {} 个问题，请修复后再上线评测。".format(total_errors))
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
