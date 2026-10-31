"""Pytest 共享配置：把 ``backend-python`` 加入 ``sys.path``，以便测试用
``services.assistant_core.intent_router`` 这种包路径直接 import，
而不需要先把 backend-python 安装为可编辑包。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent  # .../backend-python
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


@pytest.fixture(autouse=True)
def _reset_skill_first_llm_health():
    try:
        from services.assistant_core.skill_first import llm_health
    except Exception:
        yield
        return
    llm_health.reset()
    yield
    llm_health.reset()
