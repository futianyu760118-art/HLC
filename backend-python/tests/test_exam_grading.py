"""考试判分纯函数测试（Chunk 4 核心）。

判分规则：
- single/judge: 完全匹配满分，否则 0
- multiple: 全对满分；漏选（子集且非空且不全）半分；含错选或空 → 0
"""

from services.exam_grading import grade_attempt, is_passed


def _paper():
    return [
        {'id': 'q1', 'type': 'single', 'options': ['A', 'B', 'C', 'D'], 'answer': [1], 'score': 10},
        {'id': 'q2', 'type': 'multiple', 'options': ['A', 'B', 'C', 'D'], 'answer': [0, 2], 'score': 20},
        {'id': 'q3', 'type': 'judge', 'options': ['正确', '错误'], 'answer': [0], 'score': 10},
    ]


def test_all_correct():
    r = grade_attempt(_paper(), {'q1': [1], 'q2': [0, 2], 'q3': [0]})
    assert r['score'] == 40
    assert r['totalScore'] == 40
    assert all(d['correct'] for d in r['details'])


def test_single_wrong():
    r = grade_attempt(_paper(), {'q1': [0], 'q2': [0, 2], 'q3': [0]})
    assert r['score'] == 30
    assert r['details'][0]['awarded'] == 0
    assert r['details'][0]['correct'] is False


def test_multiple_partial_half_score():
    """漏选：选了 [0]（正确子集），应得半分 10。"""
    r = grade_attempt(_paper(), {'q1': [1], 'q2': [0], 'q3': [0]})
    assert r['score'] == 30
    assert r['details'][1]['awarded'] == 10
    assert r['details'][1]['correct'] is False


def test_multiple_with_wrong_choice_zero():
    """含错选：选了 [0,1,2]（含错误项 1），得 0。"""
    r = grade_attempt(_paper(), {'q1': [1], 'q2': [0, 1, 2], 'q3': [0]})
    assert r['score'] == 20
    assert r['details'][1]['awarded'] == 0


def test_multiple_all_wrong_zero():
    r = grade_attempt(_paper(), {'q1': [1], 'q2': [1, 3], 'q3': [0]})
    assert r['score'] == 20
    assert r['details'][1]['awarded'] == 0


def test_judge_wrong():
    r = grade_attempt(_paper(), {'q1': [1], 'q2': [0, 2], 'q3': [1]})
    assert r['score'] == 30


def test_empty_answers():
    r = grade_attempt(_paper(), {})
    assert r['score'] == 0
    assert all(d['awarded'] == 0 for d in r['details'])


def test_string_index_tolerance():
    """前端可能传字符串索引 '1'，应容错。"""
    r = grade_attempt(_paper(), {'q1': ['1'], 'q2': ['0', '2'], 'q3': ['0']})
    assert r['score'] == 40


def test_unanswered_question_still_in_details():
    r = grade_attempt(_paper(), {'q1': [1]})
    assert len(r['details']) == 3
    assert r['details'][2]['actual'] == []
    assert r['details'][2]['awarded'] == 0


def test_details_contain_expected_and_actual():
    r = grade_attempt(_paper(), {'q1': [0]})
    d = r['details'][0]
    assert d['expected'] == [1]
    assert d['actual'] == [0]


def test_is_passed():
    assert is_passed(30, 24) is True
    assert is_passed(20, 24) is False
    assert is_passed(24, 24) is True  # 边界：等于及格分算过


def test_decimal_precision():
    """半分要精确（不出现浮点误差）。"""
    paper = [{'id': 'q', 'type': 'multiple', 'answer': [0, 1, 2], 'score': 5}]
    r = grade_attempt(paper, {'q': [0]})  # 漏选 → 2.5
    assert r['score'] == 2.5
