"""Retry behavior of the ClinicalTrials.gov HTTP client.

urlopen is monkeypatched (the client uses urllib, not httpx) and time.sleep is
stubbed so the back-off adds no real wall-clock delay.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from app.clinicaltrials import client


class _FakeResponse:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://x", code=code, msg="boom", hdrs=None, fp=io.BytesIO(b"")
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda _s: None)


def _patch_urlopen(monkeypatch, side_effects):
    """side_effects: list of either Exception instances (raised) or dicts (returned)."""
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        i = calls["n"]
        calls["n"] += 1
        effect = side_effects[i]
        if isinstance(effect, Exception):
            raise effect
        return _FakeResponse(effect)

    monkeypatch.setattr(client.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_retries_then_succeeds_after_transient_503(monkeypatch):
    calls = _patch_urlopen(monkeypatch, [_http_error(503), {"totalCount": 7}])
    assert client.count_studies({"query.term": "x"}) == 7
    assert calls["n"] == 2


def test_retries_on_url_error_then_succeeds(monkeypatch):
    calls = _patch_urlopen(
        monkeypatch, [urllib.error.URLError("conn reset"), {"totalCount": 3}]
    )
    assert client.count_studies({"query.term": "x"}) == 3
    assert calls["n"] == 2


def test_retries_on_timeout_then_succeeds(monkeypatch):
    calls = _patch_urlopen(monkeypatch, [TimeoutError("read timed out"), {"totalCount": 1}])
    assert client.count_studies({"query.term": "x"}) == 1
    assert calls["n"] == 2


def test_client_error_4xx_fails_fast_without_retry(monkeypatch):
    calls = _patch_urlopen(monkeypatch, [_http_error(400), {"totalCount": 99}])
    with pytest.raises(urllib.error.HTTPError):
        client.count_studies({"query.term": "x"})
    assert calls["n"] == 1  # no retry on a 400


def test_gives_up_after_four_failed_attempts(monkeypatch):
    calls = _patch_urlopen(monkeypatch, [_http_error(503)] * 4)
    with pytest.raises(urllib.error.HTTPError):
        client.count_studies({"query.term": "x"})
    assert calls["n"] == 4
