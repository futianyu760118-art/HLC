"""Unit tests for the intent router FeatureFlag (Task 3.1).

Covers Requirements 8.1, 8.4, 8.5:

* When ``v2_enabled=False`` every ``user_id`` must yield ``False`` (8.1).
* Bucketing by ``sha1(user_id)`` mod 100 must respect ``rollout_pct``: 10%
  rollout has to land within [5%, 15%] over 1000 random ids (8.4).
* ``rollout_pct=100`` always allows; ``rollout_pct=0`` always denies (8.4).
* ``reload()`` makes the next call see a freshly read environment (8.5).
"""

from __future__ import annotations

import os
import sys
import uuid

import pytest

# Ensure ``backend-python`` is on sys.path so we can import the package using
# its real qualified name regardless of where pytest is invoked from.
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.assistant_core.intent_router import feature_flag  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_flag(monkeypatch):
    """Each test starts with a clean, empty environment for the flag vars."""

    monkeypatch.delenv("ASSISTANT_INTENT_ROUTER_V2_ENABLED", raising=False)
    monkeypatch.delenv("ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT", raising=False)
    feature_flag.reload()
    yield
    feature_flag.reload()


def _set_env(monkeypatch, enabled: str, pct: str) -> None:
    monkeypatch.setenv("ASSISTANT_INTENT_ROUTER_V2_ENABLED", enabled)
    monkeypatch.setenv("ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT", pct)
    feature_flag.reload()


def test_disabled_master_switch_returns_false_for_any_user(monkeypatch):
    """v2_enabled=False must override even rollout_pct=100."""

    _set_env(monkeypatch, "false", "100")

    for _ in range(50):
        user_id = uuid.uuid4().hex
        assert feature_flag.is_enabled_for(user_id) is False

    # Empty / missing user_id is also rejected.
    assert feature_flag.is_enabled_for("") is False
    assert feature_flag.is_enabled_for(None) is False


def test_rollout_pct_zero_denies_everyone(monkeypatch):
    _set_env(monkeypatch, "true", "0")

    for _ in range(200):
        assert feature_flag.is_enabled_for(uuid.uuid4().hex) is False


def test_rollout_pct_full_allows_everyone(monkeypatch):
    _set_env(monkeypatch, "true", "100")

    for _ in range(200):
        assert feature_flag.is_enabled_for(uuid.uuid4().hex) is True


def test_rollout_pct_ten_keeps_ratio_in_band(monkeypatch):
    """With 1000 random ids the True ratio for 10% rollout falls in [5%, 15%]."""

    _set_env(monkeypatch, "true", "10")

    sample_size = 1000
    enabled = sum(
        1 for _ in range(sample_size) if feature_flag.is_enabled_for(uuid.uuid4().hex)
    )
    ratio = enabled / sample_size

    assert 0.05 <= ratio <= 0.15, (
        f"Expected ratio in [0.05, 0.15] for rollout_pct=10, got {ratio:.3f}"
    )


def test_bucketing_is_stable_for_same_user(monkeypatch):
    """The same user_id consistently lands in the same bucket."""

    _set_env(monkeypatch, "true", "50")

    user_id = "stable-user-123"
    first = feature_flag.is_enabled_for(user_id)
    for _ in range(20):
        assert feature_flag.is_enabled_for(user_id) is first


def test_invalid_rollout_pct_falls_back_to_zero(monkeypatch):
    _set_env(monkeypatch, "true", "37")  # 37 is not in {0,1,10,50,100}

    for _ in range(50):
        assert feature_flag.is_enabled_for(uuid.uuid4().hex) is False


def test_truthy_alternatives_for_master_switch(monkeypatch):
    for value in ("1", "true", "TRUE", "yes"):
        monkeypatch.setenv("ASSISTANT_INTENT_ROUTER_V2_ENABLED", value)
        monkeypatch.setenv("ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT", "100")
        feature_flag.reload()

        assert feature_flag.is_enabled_for("any-user") is True

    # Sanity: capitalization variants outside the allow-list are rejected.
    monkeypatch.setenv("ASSISTANT_INTENT_ROUTER_V2_ENABLED", "True")
    monkeypatch.setenv("ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT", "100")
    feature_flag.reload()
    assert feature_flag.is_enabled_for("any-user") is False


def test_reload_picks_up_new_values_on_next_call(monkeypatch):
    """A reload after env changes must take effect on the next call (Req 8.5)."""

    _set_env(monkeypatch, "false", "0")
    user_id = "switcher-user"
    assert feature_flag.is_enabled_for(user_id) is False

    # Flip the master switch and full rollout.
    monkeypatch.setenv("ASSISTANT_INTENT_ROUTER_V2_ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT", "100")
    feature_flag.reload()

    assert feature_flag.is_enabled_for(user_id) is True

    # And back off.
    monkeypatch.setenv("ASSISTANT_INTENT_ROUTER_V2_ENABLED", "false")
    feature_flag.reload()
    assert feature_flag.is_enabled_for(user_id) is False


def test_changes_without_reload_do_not_take_effect(monkeypatch):
    """Without a reload the cached state is preserved (lazy reload contract)."""

    _set_env(monkeypatch, "true", "100")
    assert feature_flag.is_enabled_for("u") is True

    # Mutating env without reload() must keep the previous decision.
    monkeypatch.setenv("ASSISTANT_INTENT_ROUTER_V2_ENABLED", "false")
    assert feature_flag.is_enabled_for("u") is True

    feature_flag.reload()
    assert feature_flag.is_enabled_for("u") is False
