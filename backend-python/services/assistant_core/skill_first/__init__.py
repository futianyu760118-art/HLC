"""Skill-first agent runtime primitives."""

from .cards import AgentSkillCard, all_cards, get_card
from .semantic_index import RecallResult, recall_skills

__all__ = [
    'AgentSkillCard',
    'RecallResult',
    'SkillPlan',
    'all_cards',
    'get_card',
    'plan_skill',
    'recall_skills',
]


def __getattr__(name):
    if name in {'SkillPlan', 'plan_skill'}:
        from .planner import SkillPlan, plan_skill
        return {'SkillPlan': SkillPlan, 'plan_skill': plan_skill}[name]
    raise AttributeError(name)
