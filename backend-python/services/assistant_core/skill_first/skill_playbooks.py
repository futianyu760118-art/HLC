"""Compatibility wrapper for legacy Skill-first playbook helpers.

The playbook owner is now ``assistant_core.agent_kernel.skill_playbook``. This
module remains importable for old tests/tools only and must not be used by the
ordinary assistant mainline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..agent_kernel.skill_playbook import (
    SkillPlaybookGuide as SkillPlaybook,
    SkillPlaybookGuideRegistry as SkillPlaybookRegistry,
    build_card_playbook_guide_registry,
    discover_skill_playbook_guides,
    format_available_skill_guides,
)
from .cards import AgentSkillCard


def discover_skill_playbooks(root: Path | None = None) -> list[SkillPlaybook]:
    return discover_skill_playbook_guides(root)


def playbook_from_card(card: AgentSkillCard) -> SkillPlaybook:
    return build_card_playbook_guide_registry([card.id]).get(card.id)  # type: ignore[return-value]


def build_card_playbook_registry(skill_ids: Iterable[str] | None = None) -> SkillPlaybookRegistry:
    return build_card_playbook_guide_registry(list(skill_ids) if skill_ids is not None else None)


def format_available_skills_block(registry: SkillPlaybookRegistry) -> str:
    return format_available_skill_guides(registry)


__all__ = [
    'SkillPlaybook',
    'SkillPlaybookRegistry',
    'build_card_playbook_registry',
    'discover_skill_playbooks',
    'format_available_skills_block',
]
