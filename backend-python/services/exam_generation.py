"""AI 出题 service：根据培训资料用 LLM 生成题目（单选/多选/判断）。

设计：
- 复用 services/assistant_core/llm_client.json_chat_profile（结构化 JSON + 模型分档）
- use_case='exam_generation'，管理员可在 p-ai_model_settings 为出题单独配模型
- normalize 层校验/规范化每道题；非法题目过滤
- 输入源：课程内容文本（章节标题/附件文本/管理员粘贴）

仿 services/interview_analysis.py 的「system+user 双消息 + 内嵌 JSON schema」模式。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger('hengpintong.exam_generation')

VALID_TYPES = {'single', 'multiple', 'judge'}
# 判 断 题统一给两个选项
JUDGE_OPTIONS = ['正确', '错误']


def build_prompt(source_text: str, count: int, types: List[str]) -> str:
    """构造 user prompt（内嵌 JSON schema，仿 interview_analysis.py）。"""
    types_cn = {'single': '单选', 'multiple': '多选', 'judge': '判断'}
    types_desc = '、'.join(types_cn.get(t, t) for t in types)
    # 截断超长输入，避免 token 爆炸
    trimmed = (source_text or '').strip()[:6000]
    return f"""请根据以下培训资料，生成 {count} 道考试题目，题型从【{types_desc}】中合理分配。

【培训资料】
{trimmed}

【题目要求】
1. 题目必须紧扣培训资料内容，不得臆造资料中未出现的信息。
2. 单选题给 4 个选项（A/B/C/D）；多选题给 4 个选项；判断题固定为「正确/错误」两个选项。
3. 每题给出正确答案（选项的 0-based 索引数组）和解析。
4. 难度 1（最易）到 5（最难）。
5. 选项不要有明显提示答案的表述（如「以上都对」）。

【输出要求】严格按以下 JSON 格式返回，不要 markdown 代码块，不要任何其他文字：
{{
  "questions": [
    {{
      "type": "single",
      "stem": "题干文本？",
      "options": ["选项A", "选项B", "选项C", "选项D"],
      "answer": [1],
      "explanation": "为什么选 B",
      "difficulty": 3
    }},
    {{
      "type": "multiple",
      "stem": "下列哪些是正确的？（多选）",
      "options": ["选项A", "选项B", "选项C", "选项D"],
      "answer": [0, 2],
      "explanation": "解析",
      "difficulty": 4
    }},
    {{
      "type": "judge",
      "stem": "判断题题干。",
      "options": ["正确", "错误"],
      "answer": [0],
      "explanation": "解析",
      "difficulty": 2
    }}
  ]
}}"""


def normalize_question(raw: Any, allowed_types: List[str]) -> Optional[Dict[str, Any]]:
    """规范化单道题。返回 None 表示丢弃。"""
    if not isinstance(raw, dict):
        return None
    qtype = str(raw.get('type') or '').strip().lower()
    # 中英文别名归一
    type_map = {
        '单选': 'single', '单选题': 'single', 'danxuanti': 'single', 'single_choice': 'single',
        '多选': 'multiple', '多选题': 'multiple', 'duoxuanti': 'multiple', 'multiple_choice': 'multiple',
        '判断': 'judge', '判断题': 'judge', 'panduanti': 'judge', 'true_false': 'judge',
    }
    qtype = type_map.get(qtype, qtype)
    if qtype not in VALID_TYPES:
        return None
    if allowed_types and qtype not in allowed_types:
        return None

    stem = (raw.get('stem') or '').strip()
    if not stem:
        return None

    # 选项处理
    options = raw.get('options') or []
    if qtype == 'judge':
        options = JUDGE_OPTIONS
    else:
        if not isinstance(options, list) or len(options) < 2:
            return None
        options = [str(o).strip() for o in options if str(o).strip()]
        if len(options) < 2:
            return None

    # 答案索引处理
    answer_raw = raw.get('answer')
    if answer_raw is None:
        return None
    if isinstance(answer_raw, (int, float, str)):
        answer_raw = [answer_raw]
    try:
        answer_idx = sorted({int(a) for a in answer_raw})
    except (TypeError, ValueError):
        return None
    if not answer_idx:
        return None
    # 越界校验
    if any(i < 0 or i >= len(options) for i in answer_idx):
        return None
    # 多选至少 2 个答案，单选/判断恰好 1 个
    if qtype in ('single', 'judge') and len(answer_idx) != 1:
        # AI 偶尔给单选多个答案：取第一个
        answer_idx = [answer_idx[0]]
    if qtype == 'multiple' and len(answer_idx) < 1:
        return None

    # 难度 clamp 1-5
    try:
        difficulty = int(raw.get('difficulty')) if raw.get('difficulty') is not None else 3
    except (TypeError, ValueError):
        difficulty = 3
    difficulty = max(1, min(5, difficulty))

    return {
        'type': qtype,
        'stem': stem,
        'options': options,
        'answer': answer_idx,
        'explanation': (str(raw.get('explanation') or '').strip()) or None,
        'difficulty': difficulty,
    }


def generate_questions(source_text: str,
                       count: int = 5,
                       types: Optional[List[str]] = None,
                       llm_caller=None) -> List[Dict[str, Any]]:
    """用 LLM 生成题目，返回规范化后的题目列表。

    Args:
        source_text: 培训资料文本。
        count: 生成题数（clamp 到 1-20）。
        types: 题型子集，默认全部三种。
        llm_caller: 注入的调用器（测试用），签名 (messages, *, temperature, max_tokens,
                    use_case) -> dict|None。默认用 llm_client.json_chat_profile。

    Returns:
        规范化题目列表 [{type, stem, options, answer, explanation, difficulty}, ...]
    """
    types = types or ['single', 'multiple', 'judge']
    types = [t for t in types if t in VALID_TYPES] or ['single']
    count = max(1, min(20, int(count or 5)))

    messages = [
        {'role': 'system', 'content': '你是企业培训出题专家。严格只返回 JSON 对象，不要任何其他文字、不要 markdown 代码块。'},
        {'role': 'user', 'content': build_prompt(source_text, count, types)},
    ]

    if llm_caller is None:
        from services.assistant_core import llm_client
        def llm_caller(msgs, *, temperature, max_tokens, use_case):
            return llm_client.json_chat_profile(
                'standard', msgs,
                temperature=temperature, max_tokens=max_tokens,
                use_case=use_case,
                resource_domain='exam_ai',
            )

    try:
        result = llm_caller(
            messages,
            temperature=0.5,
            max_tokens=2500,
            use_case='exam_generation',
        )
    except Exception as exc:
        logger.warning('exam_generation_llm_failed', extra={'error': str(exc)})
        return []

    if not isinstance(result, dict):
        return []
    raw_questions = result.get('questions') or []
    if not isinstance(raw_questions, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for raw in raw_questions:
        q = normalize_question(raw, types)
        if q:
            normalized.append(q)
    logger.info('exam_generation_done',
                extra={'raw': len(raw_questions), 'normalized': len(normalized), 'requested': count})
    return normalized
