"""Tests for the chat agent loop and source registry (stubbed provider, no network)."""
import app.chat.agent as agent_mod
import app.chat.tools as tools_mod
from app.chat.tools import SourceRegistry
from app.llm.chat_providers import ToolCall, TurnResult


class _FakeProvider:
    """Turn 1 calls a tool; turn 2 answers with a citation."""

    def __init__(self):
        self.turn = 0

    def build_messages(self, system, history, user):
        return []

    def stream_turn(self, messages, tools):
        self.turn += 1
        if self.turn == 1:
            yield {"type": "text", "text": "Checking. "}
            tc = ToolCall(id="t1", name="search_pubmed", arguments={"query": "x"})
            yield {"type": "turn_end", "turn": TurnResult("Checking. ", [tc], None)}
        else:
            yield {"type": "text", "text": "It is a PD-1 inhibitor [1]."}
            yield {"type": "turn_end",
                   "turn": TurnResult("It is a PD-1 inhibitor [1].", [], None)}

    def append_assistant_turn(self, messages, turn):
        pass

    def append_tool_results(self, messages, results):
        pass


def _fake_pubmed(args, registry):
    src = registry.add("pubmed:999", {
        "type": "pubmed", "id": "999", "title": "PD-1 blockade",
        "url": "http://x", "journal": "NEJM", "year": "2019", "authors": ["Smith J"],
    })
    return "[1] PD-1 blockade abstract", [src], []


def test_chat_loop_runs_tool_then_answers(monkeypatch):
    monkeypatch.setitem(tools_mod.TOOL_RUNNERS, "search_pubmed", _fake_pubmed)
    monkeypatch.setattr(agent_mod, "get_chat_provider", lambda: _FakeProvider())

    events = list(agent_mod.run_chat("what is pembrolizumab"))
    kinds = [e["type"] for e in events]

    assert "tool_start" in kinds
    assert "sources" in kinds
    assert kinds[-1] == "done"

    answer = "".join(e["text"] for e in events if e["type"] == "token")
    assert "[1]" in answer

    sources = [e for e in events if e["type"] == "sources"][-1]["sources"]
    assert sources[0]["index"] == 1
    assert sources[0]["title"] == "PD-1 blockade"


def test_tool_start_carries_label(monkeypatch):
    monkeypatch.setitem(tools_mod.TOOL_RUNNERS, "search_pubmed", _fake_pubmed)
    monkeypatch.setattr(agent_mod, "get_chat_provider", lambda: _FakeProvider())
    events = list(agent_mod.run_chat("q"))
    start = next(e for e in events if e["type"] == "tool_start")
    assert start["tool"] == "search_pubmed"
    assert start["label"] == "Searching PubMed"


def test_tool_end_pairs_with_start_and_summarizes(monkeypatch):
    monkeypatch.setitem(tools_mod.TOOL_RUNNERS, "search_pubmed", _fake_pubmed)
    monkeypatch.setattr(agent_mod, "get_chat_provider", lambda: _FakeProvider())
    events = list(agent_mod.run_chat("q"))
    start = next(e for e in events if e["type"] == "tool_start")
    end = next(e for e in events if e["type"] == "tool_end")
    # start/end share a step id so the frontend can match them
    assert start["id"] == end["id"]
    assert end["result"] == "Found 1 source"


def test_source_registry_dedupes_and_numbers():
    reg = SourceRegistry()
    a = reg.add("pubmed:1", {"type": "pubmed", "title": "A"})
    b = reg.add("pubmed:2", {"type": "pubmed", "title": "B"})
    a_again = reg.add("pubmed:1", {"type": "pubmed", "title": "A"})
    assert a["index"] == 1 and b["index"] == 2
    assert a_again["index"] == 1          # same key → same number
    assert len(reg.sources) == 2          # no duplicate entry
