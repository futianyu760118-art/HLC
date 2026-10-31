"""Runtime model profiles and AI-agent feature settings.

Settings live in the existing ``settings`` table so administrators can tune
models without rebuilding containers. Environment variables remain the
bootstrap fallback for installations without saved settings.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Dict, Optional


SETTING_KEY = 'assistantModelSettings'


def defaults() -> Dict[str, Any]:
    default_model = os.getenv('ASSISTANT_MODEL', 'deepseek-ai/DeepSeek-V4-Flash')
    fast_model = os.getenv('ASSISTANT_FAST_MODEL', default_model)
    return {
        'provider': 'siliconflow',
        'smallModel': os.getenv('ASSISTANT_SMALL_MODEL', fast_model),
        'standardModel': os.getenv('ASSISTANT_STANDARD_MODEL', 'deepseek-ai/DeepSeek-V3.2'),
        'strongModel': os.getenv('ASSISTANT_STRONG_MODEL', 'deepseek-ai/DeepSeek-V4-Pro'),
        'useCases': {
            'dialogue': 'standard',
            'dataSummary': 'small',
            'genericGeneration': 'standard',
            'evidenceAnalysis': 'strong',
            'compositePlanning': 'strong',
            'skillPlanning': 'small',
            'promptOptimization': 'strong',
            'intentReasoning': 'strong',
        },
        'features': {
            'skillPlanning': True,
            'promptOptimization': True,
            'intentReasoning': True,
            'evidenceReasoning': True,
            'multiAgentReasoning': True,
        },
    }


def _merge(base: Dict[str, Any], saved: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = deepcopy(base)
    if not isinstance(saved, dict):
        return result
    for key in ('provider', 'smallModel', 'standardModel', 'strongModel'):
        if isinstance(saved.get(key), str) and saved[key].strip():
            result[key] = saved[key].strip()
    if isinstance(saved.get('useCases'), dict):
        for key, value in saved['useCases'].items():
            if key in result['useCases'] and value in ('small', 'standard', 'strong'):
                result['useCases'][key] = value
    if isinstance(saved.get('features'), dict):
        for key, value in saved['features'].items():
            if key in result['features'] and isinstance(value, bool):
                result['features'][key] = value
    return result


def load_settings() -> Dict[str, Any]:
    try:
        from models import Setting

        row = Setting.query.get(SETTING_KEY)
        return _merge(defaults(), row.value if row else None)
    except Exception:
        return defaults()


def save_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    from models import Setting, db

    normalized = _merge(defaults(), payload)
    row = Setting.query.get(SETTING_KEY)
    if row:
        row.value = normalized
    else:
        db.session.add(Setting(key=SETTING_KEY, value=normalized))
    db.session.commit()
    return normalized


_USE_CASE_ALIASES = {
    'dialogue': 'dialogue',
    'data_summary': 'dataSummary',
    'generic_generation': 'genericGeneration',
    'interview_questions': 'genericGeneration',
    'exam_generation': 'genericGeneration',
    'course_qa': 'genericGeneration',
    'hr_email_draft': 'genericGeneration',
    'job_posting': 'genericGeneration',
    'candidate_compare': 'evidenceAnalysis',
    'analysis_report': 'evidenceAnalysis',
    'candidate_assessment': 'evidenceAnalysis',
    'person_assessment': 'evidenceAnalysis',
    'person_evidence_answer': 'evidenceAnalysis',
    'composite_planning': 'compositePlanning',
    'skill_planning': 'skillPlanning',
    'skill_first_understanding': 'skillPlanning',
    'skill_first_planner': 'skillPlanning',
    'skill_first_slot_reference': 'skillPlanning',
    'skill_first_grounded_answer': 'genericGeneration',
    'prompt_optimization': 'promptOptimization',
    'intent_reasoning': 'intentReasoning',
}


def profile_for_use_case(default_profile: str, use_case: Optional[str] = None) -> str:
    settings = load_settings()
    key = _USE_CASE_ALIASES.get(use_case or '', use_case or '')
    if key == 'evidenceAnalysis' and not (settings.get('features') or {}).get('evidenceReasoning', True):
        return default_profile
    configured = (settings.get('useCases') or {}).get(key)
    return configured if configured in ('small', 'standard', 'strong') else default_profile


def model_for_profile(profile: str, use_case: Optional[str] = None) -> str:
    settings = load_settings()
    selected = profile_for_use_case(profile, use_case)
    return settings.get({
        'small': 'smallModel',
        'strong': 'strongModel',
    }.get(selected, 'standardModel')) or defaults()['standardModel']


def feature_enabled(name: str) -> bool:
    return bool((load_settings().get('features') or {}).get(name, False))


def public_settings() -> Dict[str, Any]:
    settings = load_settings()
    settings['effectiveModels'] = {
        key: model_for_profile(profile, key)
        for key, profile in (settings.get('useCases') or {}).items()
    }
    return settings
