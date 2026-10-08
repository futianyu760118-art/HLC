"""Runtime knobs for Skill-first LLM participation.

The Agent Kernel lets the model participate in understanding, planning and
slot/reference refinement, but ordinary product traffic needs a hard latency
budget. Strong Skill Card recall can recover through guarded schema execution,
so a slow model should not hold the whole request hostage.
"""

from __future__ import annotations

import os


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    return raw.strip().lower() not in {'0', 'false', 'off', 'no'}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 120) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(value, maximum))


def understanding_timeout() -> int:
    return _env_int('ASSISTANT_SKILL_FIRST_UNDERSTANDING_TIMEOUT', 8, minimum=2, maximum=60)


def planner_timeout() -> int:
    return _env_int('ASSISTANT_SKILL_FIRST_PLANNER_TIMEOUT', 18, minimum=2, maximum=60)


def slot_reference_timeout() -> int:
    return _env_int('ASSISTANT_SKILL_FIRST_SLOT_TIMEOUT', 8, minimum=2, maximum=60)


def synthesis_timeout() -> int:
    return _env_int('ASSISTANT_SKILL_FIRST_SYNTHESIS_TIMEOUT', 5, minimum=1, maximum=30)


def playbook_timeout() -> int:
    return _env_int('ASSISTANT_SKILL_FIRST_PLAYBOOK_TIMEOUT', 6, minimum=1, maximum=30)


def health_circuit_enabled() -> bool:
    return _env_bool('ASSISTANT_SKILL_FIRST_LLM_HEALTH_CIRCUIT', True)


def health_failure_threshold() -> int:
    return _env_int('ASSISTANT_SKILL_FIRST_LLM_HEALTH_FAILURE_THRESHOLD', 8, minimum=1, maximum=40)


def health_cooldown_seconds() -> int:
    return _env_int('ASSISTANT_SKILL_FIRST_LLM_HEALTH_COOLDOWN_SECONDS', 90, minimum=5, maximum=900)


__all__ = [
    'health_circuit_enabled',
    'health_cooldown_seconds',
    'health_failure_threshold',
    'understanding_timeout',
    'planner_timeout',
    'playbook_timeout',
    'slot_reference_timeout',
    'synthesis_timeout',
]
