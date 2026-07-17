"""
Streaming chat agent loop.

Drives a provider-agnostic tool-calling loop and yields a flat sequence of
events for the SSE endpoint to serialize:

  {"type": "token", "text": ...}          incremental assistant text
  {"type": "tool_start", "tool": ...,     a tool call began
                          "label": ...}
  {"type": "sources", "sources": [...]}   citation sources discovered so far
  {"type": "visualization", "payload":..} a chart to render inline
  {"type": "done"}                        turn complete

The loop runs until the model produces a turn with no tool calls (its final
answer) or hits chat_max_turns.
"""
from __future__ import annotations

from typing import Iterator

import structlog

from app.chat.prompt import CHAT_SYSTEM_PROMPT
from app.chat.tools import CHAT_TOOLS, SourceRegistry, run_tool, tool_label
from app.config import get_settings
from app.llm.chat_providers import get_chat_provider

log = structlog.get_logger(__name__)


def run_chat(user_message: str, history: list[dict] | None = None) -> Iterator[dict]:
    """
    Run one chat turn as a stream of events.

    `history` is a neutral list of {"role": "user"|"assistant", "content": str}
    from prior turns (text only — tool round-trips are re-derived per request).
    """
    history = history or []
    provider = get_chat_provider()
    max_turns = get_settings().chat_max_turns
    registry = SourceRegistry()

    messages = provider.build_messages(CHAT_SYSTEM_PROMPT, history, user_message)
    log.info("chat.start", provider=type(provider).__name__, message=user_message[:200])

    for turn_idx in range(max_turns):
        turn = None
        for event in provider.stream_turn(messages, CHAT_TOOLS):
            if event["type"] == "text":
                yield {"type": "token", "text": event["text"]}
            elif event["type"] == "turn_end":
                turn = event["turn"]

        if turn is None:  # provider ended without a turn_end (shouldn't happen)
            break

        if not turn.tool_calls:
            log.info("chat.done", turns=turn_idx + 1, sources=len(registry.sources))
            break

        provider.append_assistant_turn(messages, turn)

        results = []
        for step_i, tc in enumerate(turn.tool_calls):
            step_id = f"{turn_idx}-{step_i}"
            yield {
                "type": "tool_start",
                "id": step_id,
                "tool": tc.name,
                "label": tool_label(tc.name),
                "detail": _call_detail(tc.name, tc.arguments),
            }
            log.info("chat.tool", name=tc.name, arguments=tc.arguments)
            model_text, new_sources, extra_events = run_tool(tc.name, tc.arguments, registry)
            results.append((tc, model_text))
            for ev in extra_events:
                yield ev
            yield {
                "type": "tool_end",
                "id": step_id,
                "tool": tc.name,
                "result": _result_summary(tc.name, new_sources, extra_events),
            }
            if registry.sources:
                yield {"type": "sources", "sources": registry.sources}

        provider.append_tool_results(messages, results)
    else:
        # Loop exhausted without a tool-free final turn.
        yield {"type": "token",
               "text": "\n\n_(Reached the reasoning limit for this turn.)_"}

    if registry.sources:
        yield {"type": "sources", "sources": registry.sources}
    yield {"type": "done"}


def _call_detail(tool: str, args: dict) -> str:
    """Short human phrase describing what a tool call is looking for."""
    if tool == "search_pubmed":
        return args.get("query", "")
    if tool == "search_clinical_trials":
        parts = [args.get("condition"), args.get("intervention"),
                 args.get("query_term"), args.get("status")]
        return " · ".join(p for p in parts if p)
    if tool == "create_visualization":
        return args.get("query", "")
    return ""


def _result_summary(tool: str, new_sources: list, extra_events: list) -> str:
    """One-line outcome shown once a step completes."""
    if tool == "create_visualization":
        viz = next((e for e in extra_events if e.get("type") == "visualization"), None)
        if viz:
            v = (viz["payload"].get("visualization") or {})
            return f"Rendered {v.get('type', 'chart').replace('_', ' ')}"
        return "No chart produced"
    n = len(new_sources)
    return f"Found {n} source{'s' if n != 1 else ''}" if n else "No results"
