"""Tests for the code-gated 'no data' notice path (finalize_notice + loop gate)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.agent import loop as agent_loop
from app.agent import registry
from app.config import get_settings
from app.models import QueryRequest, VisualizationResponse
from app.tools.finalize import finalize_notice


def _tc(name: str, args: dict) -> SimpleNamespace:
    return SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _msg(*calls: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(role="assistant", content=None, tool_calls=list(calls))


def _script_complete(script: list[SimpleNamespace]):
    """Fake provider.complete that replays a scripted list of assistant messages."""
    seq = list(script)

    def fake(messages, tools, tool_choice="required"):
        if seq:
            return seq.pop(0)
        # After the script runs out, keep attempting to decline (drives gate/backstop tests).
        return _msg(_tc("finalize_notice", {"message": "none"}))

    return fake


def _stub_search(monkeypatch, *, dataset_id):
    monkeypatch.setitem(
        registry.TOOL_FNS,
        "search_trials",
        lambda **k: {
            "dataset_id": dataset_id,
            "total_count": 5 if dataset_id else 0,
            "fetched_count": 5 if dataset_id else 0,
            "sample_titles": [],
        },
    )


def test_finalize_notice_shape():
    r = finalize_notice("nope")
    assert isinstance(r, VisualizationResponse)
    assert r.visualization is None
    assert r.message == "nope"
    assert r.response_metadata.total_count == 0
    assert r.response_metadata.query_interpretation == "nope"


def test_notice_honored_when_no_data(monkeypatch):
    _stub_search(monkeypatch, dataset_id=None)
    monkeypatch.setattr("app.llm.provider.complete", _script_complete([
        _msg(_tc("search_trials", {"query_term": "zzz"})),
        _msg(_tc("finalize_notice", {"message": "No trials found."})),
    ]))
    out = agent_loop.run_agent(QueryRequest(query="zzz"))
    assert out.visualization is None
    assert out.message == "No trials found."


def test_notice_refused_when_data_exists(monkeypatch):
    # Data was found, so a decline must be rejected; the loop exhausts and raises.
    _stub_search(monkeypatch, dataset_id="d")
    monkeypatch.setattr(get_settings(), "agent_max_turns", 3)
    monkeypatch.setattr("app.llm.provider.complete", _script_complete([
        _msg(_tc("search_trials", {"condition": "diabetes"})),
        _msg(_tc("finalize_notice", {"message": "decline"})),
    ]))
    with pytest.raises(ValueError):
        agent_loop.run_agent(QueryRequest(query="diabetes"))


def test_backstop_returns_notice_when_no_data(monkeypatch):
    # Turn limit hit with no data ever found -> clean notice instead of ValueError.
    _stub_search(monkeypatch, dataset_id=None)
    monkeypatch.setattr(get_settings(), "agent_max_turns", 1)
    monkeypatch.setattr("app.llm.provider.complete", _script_complete([
        _msg(_tc("search_trials", {"query_term": "zzz"})),
    ]))
    out = agent_loop.run_agent(QueryRequest(query="zzz"))
    assert out.visualization is None
    assert "No clinical trials matched" in out.message
