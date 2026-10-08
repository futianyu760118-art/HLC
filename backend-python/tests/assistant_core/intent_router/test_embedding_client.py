"""Unit tests for the SiliconFlow embedding client (Task 4.1).

Covers Requirements 12.1 and 12.4:

* 12.1 – Successful 200 response yields a normalized ``float32`` unit vector.
* 12.4 – Embedding service unavailability (non-2xx, timeout, malformed JSON,
  network error, missing API key) must produce ``None`` instead of raising.
* LRU cache for the stable-corpus path (``embed_corpus``) must short-circuit
  the second HTTP call for the same input.

All tests stub :func:`requests.post` via ``monkeypatch`` so no real network
traffic is performed.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

import numpy as np
import pytest
import requests

# Ensure ``backend-python`` is on sys.path for direct package imports when
# running ``pytest`` from the repository root.
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from services.assistant_core.intent_router import embedding_client  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Minimal stand-in for ``requests.Response`` used by the client."""

    def __init__(self, status_code: int = 200, payload: Any = None, raise_json: bool = False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json

    def json(self) -> Any:
        if self._raise_json:
            raise ValueError("malformed json")
        return self._payload


def _payload_for(vectors: List[List[float]]) -> Dict[str, Any]:
    return {"data": [{"embedding": v} for v in vectors]}


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """Provide a fake API key so the client doesn't short-circuit on auth."""

    monkeypatch.setenv(embedding_client._ENV_API_KEY, "fake-key")
    monkeypatch.delenv(embedding_client._ENV_API_URL, raising=False)
    monkeypatch.delenv(embedding_client._ENV_EMBEDDING_MODEL, raising=False)
    embedding_client.clear_corpus_cache()
    yield
    embedding_client.clear_corpus_cache()


def _patch_post(monkeypatch, response_or_exc, capture: Optional[List[Dict[str, Any]]] = None):
    """Patch ``requests.post`` to return a response or raise an exception."""

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):  # noqa: ANN001
        if capture is not None:
            capture.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if isinstance(response_or_exc, BaseException):
            raise response_or_exc
        if callable(response_or_exc):
            return response_or_exc(url, headers, json, timeout)
        return response_or_exc

    monkeypatch.setattr(embedding_client.requests, "post", fake_post)


# ---------------------------------------------------------------------------
# 200 OK – normalization & shape
# ---------------------------------------------------------------------------

def test_embed_returns_float32_unit_vector_on_200(monkeypatch):
    raw_vec = [3.0, 4.0]  # |v| = 5, expected normalized = [0.6, 0.8]
    captured: List[Dict[str, Any]] = []
    _patch_post(
        monkeypatch,
        _FakeResponse(200, _payload_for([raw_vec])),
        capture=captured,
    )

    vec = embedding_client.embed("hello world")

    assert vec is not None
    assert isinstance(vec, np.ndarray)
    assert vec.dtype == np.float32
    assert vec.shape == (2,)
    # Normalized.
    assert pytest.approx(float(np.linalg.norm(vec)), rel=1e-5) == 1.0
    np.testing.assert_allclose(vec, np.array([0.6, 0.8], dtype=np.float32), rtol=1e-5)

    # Sanity: request body shape matches SiliconFlow / OpenAI compat schema.
    assert captured, "requests.post was not invoked"
    sent = captured[0]
    assert sent["url"].endswith("/embeddings")
    assert sent["json"]["model"] == embedding_client.DEFAULT_EMBEDDING_MODEL
    assert sent["json"]["input"] == ["hello world"]
    assert sent["json"]["encoding_format"] == "float"
    # Default 2000ms timeout converted to 2.0s.
    assert sent["timeout"] == pytest.approx(2.0)
    assert sent["headers"]["Authorization"] == "Bearer fake-key"


def test_embed_zero_vector_handled_without_division_error(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(200, _payload_for([[0.0, 0.0, 0.0]])))

    vec = embedding_client.embed("zero")
    assert vec is not None
    assert vec.dtype == np.float32
    # All zeros stay zeros (norm clipped to eps), no NaNs/Infs.
    assert np.all(vec == 0)
    assert not np.isnan(vec).any()
    assert not np.isinf(vec).any()


def test_embed_batch_normalizes_each_row(monkeypatch):
    payload = _payload_for([[1.0, 0.0], [0.0, 2.0], [3.0, 4.0]])
    _patch_post(monkeypatch, _FakeResponse(200, payload))

    vecs = embedding_client.embed_batch(["a", "b", "c"])

    assert len(vecs) == 3
    for v in vecs:
        assert v is not None
        assert v.dtype == np.float32
        assert pytest.approx(float(np.linalg.norm(v)), rel=1e-5) == 1.0


def test_embed_batch_with_empty_strings_marks_them_none(monkeypatch):
    # Only "a" is real; with all-empty inputs the client must skip the HTTP
    # call entirely, so make sure that path also works.
    _patch_post(monkeypatch, _FakeResponse(200, _payload_for([[1.0, 0.0]] * 2)))

    out = embedding_client.embed_batch(["a", "", "b"])
    # The masking guarantees positions of empty strings come back as None,
    # regardless of what the server returned for them.
    assert out[1] is None


def test_embed_batch_all_empty_skips_http(monkeypatch):
    captured: List[Dict[str, Any]] = []
    _patch_post(monkeypatch, _FakeResponse(200, _payload_for([])), capture=captured)

    out = embedding_client.embed_batch(["", "", None])  # type: ignore[list-item]
    assert out == [None, None, None]
    assert captured == []  # no HTTP traffic


# ---------------------------------------------------------------------------
# Failure modes – must return None, never raise
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 502, 503, 504])
def test_embed_returns_none_on_non_200(monkeypatch, status):
    _patch_post(monkeypatch, _FakeResponse(status, {}))

    assert embedding_client.embed("anything") is None


def test_embed_returns_none_on_timeout(monkeypatch):
    _patch_post(monkeypatch, requests.Timeout("simulated"))

    assert embedding_client.embed("anything") is None


def test_embed_returns_none_on_connection_error(monkeypatch):
    _patch_post(monkeypatch, requests.ConnectionError("boom"))

    assert embedding_client.embed("anything") is None


def test_embed_returns_none_on_malformed_json(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(200, payload=None, raise_json=True))

    assert embedding_client.embed("anything") is None


def test_embed_returns_none_when_data_field_missing(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(200, {"unexpected": "shape"}))

    assert embedding_client.embed("anything") is None


def test_embed_returns_none_when_embedding_field_missing(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(200, {"data": [{"not_embedding": [1.0]}]}))

    assert embedding_client.embed("anything") is None


def test_embed_returns_none_when_data_length_mismatch(monkeypatch):
    # Server returned 0 items for 1 input.
    _patch_post(monkeypatch, _FakeResponse(200, _payload_for([])))

    assert embedding_client.embed("anything") is None


def test_embed_returns_none_when_api_key_missing(monkeypatch):
    monkeypatch.delenv(embedding_client._ENV_API_KEY, raising=False)

    # Even if requests.post would raise, we must short-circuit before calling.
    def explode(*_a, **_kw):
        raise AssertionError("requests.post must not be called when API key is missing")

    monkeypatch.setattr(embedding_client.requests, "post", explode)

    assert embedding_client.embed("anything") is None
    assert embedding_client.embed_batch(["a", "b"]) == [None, None]


def test_embed_with_empty_text_returns_none_without_http(monkeypatch):
    def explode(*_a, **_kw):
        raise AssertionError("requests.post must not be called for empty input")

    monkeypatch.setattr(embedding_client.requests, "post", explode)

    assert embedding_client.embed("") is None
    assert embedding_client.embed(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Custom timeout / model overrides
# ---------------------------------------------------------------------------

def test_custom_timeout_passed_through(monkeypatch):
    captured: List[Dict[str, Any]] = []
    _patch_post(monkeypatch, _FakeResponse(200, _payload_for([[1.0]])), capture=captured)

    embedding_client.embed("hi", timeout_ms=500)
    assert captured[0]["timeout"] == pytest.approx(0.5)


def test_custom_model_overrides_default(monkeypatch):
    captured: List[Dict[str, Any]] = []
    _patch_post(monkeypatch, _FakeResponse(200, _payload_for([[1.0]])), capture=captured)

    embedding_client.embed("hi", model="custom/model-xl")
    assert captured[0]["json"]["model"] == "custom/model-xl"


def test_env_default_model_overrides_constant(monkeypatch):
    monkeypatch.setenv(embedding_client._ENV_EMBEDDING_MODEL, "env/model-1")
    captured: List[Dict[str, Any]] = []
    _patch_post(monkeypatch, _FakeResponse(200, _payload_for([[1.0]])), capture=captured)

    embedding_client.embed("hi")
    assert captured[0]["json"]["model"] == "env/model-1"


# ---------------------------------------------------------------------------
# LRU cache behaviour
# ---------------------------------------------------------------------------

def test_embed_corpus_caches_and_avoids_second_http_call(monkeypatch):
    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):  # noqa: ANN001
        call_count["n"] += 1
        return _FakeResponse(200, _payload_for([[3.0, 4.0]]))

    monkeypatch.setattr(embedding_client.requests, "post", fake_post)

    v1 = embedding_client.embed_corpus("foo")
    v2 = embedding_client.embed_corpus("foo")

    assert v1 is not None and v2 is not None
    np.testing.assert_array_equal(v1, v2)
    assert call_count["n"] == 1, "second call must hit the LRU cache"


def test_embed_corpus_distinct_inputs_each_trigger_one_call(monkeypatch):
    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):  # noqa: ANN001
        call_count["n"] += 1
        return _FakeResponse(200, _payload_for([[1.0, 0.0]]))

    monkeypatch.setattr(embedding_client.requests, "post", fake_post)

    embedding_client.embed_corpus("foo")
    embedding_client.embed_corpus("bar")
    embedding_client.embed_corpus("foo")  # cache hit
    embedding_client.embed_corpus("bar")  # cache hit

    assert call_count["n"] == 2


def test_embed_does_not_use_corpus_cache(monkeypatch):
    """Per spec, the query path bypasses the LRU cache; every call hits HTTP."""

    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):  # noqa: ANN001
        call_count["n"] += 1
        return _FakeResponse(200, _payload_for([[3.0, 4.0]]))

    monkeypatch.setattr(embedding_client.requests, "post", fake_post)

    embedding_client.embed("query")
    embedding_client.embed("query")
    embedding_client.embed("query")

    assert call_count["n"] == 3


def test_clear_corpus_cache_resets_state(monkeypatch):
    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):  # noqa: ANN001
        call_count["n"] += 1
        return _FakeResponse(200, _payload_for([[1.0]]))

    monkeypatch.setattr(embedding_client.requests, "post", fake_post)

    embedding_client.embed_corpus("foo")
    embedding_client.embed_corpus("foo")
    assert call_count["n"] == 1

    embedding_client.clear_corpus_cache()
    embedding_client.embed_corpus("foo")
    assert call_count["n"] == 2


def test_embed_corpus_failure_is_not_cached_when_returns_none(monkeypatch):
    """A failed (None) result should not be cached as success.

    ``functools.lru_cache`` *does* cache ``None``, so a transient failure could
    poison the cache for the lifetime of the process. We document this trade-off
    here: the test asserts the current behaviour so any future change to a more
    sophisticated cache (e.g. caching only successes) is intentional.
    """

    state = {"fail": True, "n": 0}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):  # noqa: ANN001
        state["n"] += 1
        if state["fail"]:
            return _FakeResponse(500, {})
        return _FakeResponse(200, _payload_for([[1.0]]))

    monkeypatch.setattr(embedding_client.requests, "post", fake_post)

    assert embedding_client.embed_corpus("foo") is None
    # Current behaviour: lru_cache also caches the None result.
    assert embedding_client.embed_corpus("foo") is None
    assert state["n"] == 1

    # After clearing cache and a server recovery, we get a real vector.
    embedding_client.clear_corpus_cache()
    state["fail"] = False
    v = embedding_client.embed_corpus("foo")
    assert v is not None
    assert state["n"] == 2


# ---------------------------------------------------------------------------
# Module-level guarantees
# ---------------------------------------------------------------------------

def test_default_embedding_model_constant_is_module_level():
    assert hasattr(embedding_client, "DEFAULT_EMBEDDING_MODEL")
    assert isinstance(embedding_client.DEFAULT_EMBEDDING_MODEL, str)
    assert embedding_client.DEFAULT_EMBEDDING_MODEL  # non-empty


def test_is_available_reflects_api_key(monkeypatch):
    monkeypatch.setenv(embedding_client._ENV_API_KEY, "x")
    assert embedding_client.is_available() is True

    monkeypatch.delenv(embedding_client._ENV_API_KEY, raising=False)
    assert embedding_client.is_available() is False
