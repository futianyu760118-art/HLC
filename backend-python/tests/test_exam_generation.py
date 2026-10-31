"""AI 出题逻辑测试（Chunk 5）。

normalize_question + generate_questions 用 mock LLM caller，不依赖真实网络。
端点集成（generate/approve/reject）见 test_exam_flow.py。
"""

from services.exam_generation import normalize_question, generate_questions, build_prompt


# ---------- normalize_question ----------

def test_legal_single():
    q = normalize_question({'type': 'single', 'stem': '题干', 'options': ['A', 'B', 'C', 'D'],
                            'answer': [1], 'difficulty': 3}, ['single'])
    assert q and q['type'] == 'single' and q['answer'] == [1]


def test_judge_forces_two_options():
    q = normalize_question({'type': 'judge', 'stem': '判断', 'options': ['Y', 'N'], 'answer': [0]}, ['judge'])
    assert q['options'] == ['正确', '错误']
    assert q['answer'] == [0]


def test_multiple_multi_answer():
    q = normalize_question({'type': 'multiple', 'stem': '多选', 'options': ['A', 'B', 'C'],
                            'answer': [0, 2]}, ['multiple'])
    assert q['answer'] == [0, 2]


def test_single_with_multi_answer_takes_first():
    q = normalize_question({'type': 'single', 'stem': '题', 'options': ['A', 'B'], 'answer': [0, 1]}, ['single'])
    assert q['answer'] == [0]


def test_chinese_type_aliases():
    assert normalize_question({'type': '单选', 'stem': '题', 'options': ['A', 'B'], 'answer': [0]}, ['single'])['type'] == 'single'
    assert normalize_question({'type': '多选题', 'stem': '题', 'options': ['A', 'B'], 'answer': [0, 1]}, ['multiple'])['type'] == 'multiple'
    assert normalize_question({'type': 'PANDUANTI', 'stem': '题', 'options': ['Y', 'N'], 'answer': [1]}, ['judge'])['type'] == 'judge'


def test_type_not_in_allowed_rejected():
    assert normalize_question({'type': 'single', 'stem': '题', 'options': ['A', 'B'], 'answer': [0]}, ['multiple']) is None


def test_empty_stem_rejected():
    assert normalize_question({'type': 'single', 'stem': '', 'options': ['A', 'B'], 'answer': [0]}, ['single']) is None


def test_too_few_options_rejected():
    assert normalize_question({'type': 'single', 'stem': '题', 'options': ['A'], 'answer': [0]}, ['single']) is None


def test_answer_out_of_range_rejected():
    assert normalize_question({'type': 'single', 'stem': '题', 'options': ['A', 'B'], 'answer': [5]}, ['single']) is None


def test_empty_answer_rejected():
    assert normalize_question({'type': 'single', 'stem': '题', 'options': ['A', 'B'], 'answer': []}, ['single']) is None


def test_non_dict_rejected():
    assert normalize_question('not a dict', ['single']) is None


def test_difficulty_clamp_high():
    assert normalize_question({'type': 'single', 'stem': '题', 'options': ['A', 'B'], 'answer': [0], 'difficulty': 99}, ['single'])['difficulty'] == 5


def test_difficulty_clamp_low_zero():
    """difficulty=0 应 clamp 到 1，不能因 falsy 变成默认 3。"""
    assert normalize_question({'type': 'single', 'stem': '题', 'options': ['A', 'B'], 'answer': [0], 'difficulty': 0}, ['single'])['difficulty'] == 1


def test_string_answer_index():
    assert normalize_question({'type': 'single', 'stem': '题', 'options': ['A', 'B'], 'answer': '1'}, ['single'])['answer'] == [1]


# ---------- generate_questions (mock LLM) ----------

def _mock_good(msgs, *, temperature, max_tokens, use_case):
    return {'questions': [
        {'type': 'single', 'stem': '单选1', 'options': ['A', 'B', 'C', 'D'], 'answer': [1], 'explanation': '解', 'difficulty': 3},
        {'type': 'multiple', 'stem': '多选1', 'options': ['A', 'B', 'C'], 'answer': [0, 2], 'difficulty': 4},
        {'type': 'judge', 'stem': '判断1', 'options': ['正确', '错误'], 'answer': [0], 'difficulty': 2},
        {'type': 'single', 'stem': '', 'options': ['A', 'B'], 'answer': [0]},  # 非法，过滤
        {'type': 'unknown', 'stem': 'x', 'options': ['A', 'B'], 'answer': [0]},  # 非法题型
    ]}


def test_generate_filters_invalid_keeps_valid():
    qs = generate_questions('资料', count=5, llm_caller=_mock_good)
    assert len(qs) == 3
    assert [q['type'] for q in qs] == ['single', 'multiple', 'judge']


def test_generate_handles_none_response():
    assert generate_questions('资料', llm_caller=lambda *a, **k: None) == []


def test_generate_handles_exception():
    def boom(*a, **k):
        raise Exception('network down')
    assert generate_questions('资料', llm_caller=boom) == []


def test_generate_handles_non_dict_response():
    assert generate_questions('资料', llm_caller=lambda *a, **k: 'not a dict') == []


def test_generate_handles_questions_not_list():
    assert generate_questions('资料', llm_caller=lambda *a, **k: {'questions': 'oops'}) == []


def test_build_prompt_contains_source_and_count():
    p = build_prompt('XYZ资料', 7, ['single', 'multiple'])
    assert 'XYZ资料' in p
    assert '7' in p
