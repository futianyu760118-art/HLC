"""考试判分纯函数（无 DB 依赖，最易测试）。

判分规则：
- single（单选）: 答案索引完全匹配 → 满分，否则 0
- judge（判断）: 同 single（答案是一个索引，0=正确/1=错误 之类）
- multiple（多选）: 选项完全匹配 → 满分；漏选（缺正确但无错选）→ 半分；含错选 → 0

数据约定：
- 每题的 answer 是「正确选项索引列表」，如 [0, 2]
- 考生提交的 answers 是 {questionId: [selectedIndex, ...]}
- paper_snapshot 是 [{id, type, options, answer, score, stem, explanation}, ...]

返回：
    {
        'score': Decimal/float 总分,
        'totalScore': 满分,
        'details': [
            {
                'questionId', 'type', 'correct': bool(是否拿满分),
                'awarded': 该题得分, 'maxScore': 该题满分,
                'expected': [正确索引], 'actual': [考生索引],
            }
        ]
    }
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List


def _as_index_set(value) -> set:
    """把答案规范化为 int 索引集合。容错：字符串数字、嵌套列表。"""
    if value is None:
        return set()
    if isinstance(value, (int, float, str)):
        try:
            return {int(value)}
        except (TypeError, ValueError):
            return set()
    result = set()
    try:
        for v in value:
            try:
                result.add(int(v))
            except (TypeError, ValueError):
                continue
    except TypeError:
        pass
    return result


def _grade_single(expected: set, actual: set, max_score) -> Decimal:
    """单选/判断：完全匹配满分，否则 0。"""
    return Decimal(str(max_score)) if expected and expected == actual else Decimal('0')


def _grade_multiple(expected: set, actual: set, max_score) -> tuple:
    """多选：完全匹配满分；漏选(实际⊆正确且非空且不全)半分；含错选或空 0。

    返回 (得分, 是否满分)。
    """
    score = Decimal('0')
    full = False
    if expected and expected == actual:
        score = Decimal(str(max_score))
        full = True
    elif actual and actual.issubset(expected) and len(actual) < len(expected):
        # 漏选：选的都是对的，但没选全 → 半分
        score = Decimal(str(max_score)) / 2
    # 含错选（actual 不是 expected 子集）→ 0
    # 空答 → 0
    return score, full


def grade_attempt(paper_snapshot: List[dict], answers: Dict[str, list]) -> dict:
    """对一次考试判分。

    Args:
        paper_snapshot: [{id, type, answer, score}, ...]（含可能 stem/options/explanation）
        answers: {questionId: [idx,...]} 考生提交

    Returns:
        {score, totalScore, details: [...]}
    """
    details = []
    total = Decimal('0')
    max_total = Decimal('0')
    for q in paper_snapshot:
        qid = str(q.get('id'))
        qtype = (q.get('type') or '').lower()
        expected = _as_index_set(q.get('answer'))
        actual = _as_index_set(answers.get(qid))
        max_score = Decimal(str(q.get('score') or 0))
        max_total += max_score

        awarded = Decimal('0')
        full = False
        if qtype in ('single', 'judge', 'single_choice', 'true_false', 'panduanti', 'danxuanti'):
            awarded = _grade_single(expected, actual, max_score)
            full = awarded == max_score and max_score > 0
        elif qtype in ('multiple', 'multiple_choice', 'duoxuanti'):
            awarded, full = _grade_multiple(expected, actual, max_score)
        else:
            # 未知题型：按单选处理
            awarded = _grade_single(expected, actual, max_score)
            full = awarded == max_score and max_score > 0

        total += awarded
        details.append({
            'questionId': qid,
            'type': qtype,
            'correct': full,
            'awarded': float(awarded),
            'maxScore': float(max_score),
            'expected': sorted(expected),
            'actual': sorted(actual),
        })

    return {
        'score': float(total),
        'totalScore': float(max_total),
        'details': details,
    }


def is_passed(score: float, pass_score: float) -> bool:
    """是否通过。"""
    try:
        return float(score) >= float(pass_score)
    except (TypeError, ValueError):
        return False
