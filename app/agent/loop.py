"""
OpenAI tool-calling agent loop.

The agent's only job is language and control flow:
  1. Decide which search parameters to use.
  2. Decide whether to aggregate or build a network.
  3. Provide a human-readable title and axis labels.

Everything numeric stays in Python (the tools package). The agent only passes
UUIDs (dataset_id, result_id) and string field names between tool calls.
"""
from __future__ import annotations

import json
from typing import Any

import structlog

from app.agent.registry import TOOL_FNS
from app.agent.tool_schemas import TOOLS
from app.config import get_settings
from app.llm import provider
from app.models import QueryRequest, VisualizationResponse
from app.prompts import SYSTEM_PROMPT
from app.tools.finalize import finalize_notice

log = structlog.get_logger(__name__)

# Tool calls that end the loop by returning a VisualizationResponse.
_TERMINAL_TOOLS = {"finalize_visualization", "finalize_notice"}

_NO_DATA_MESSAGE = "No clinical trials matched the query, even after broadening."


def run_agent(request: QueryRequest) -> VisualizationResponse:
    # Serialize filters into the user message so the agent sees them as plain text context.
    filters = {}
    if request.filters:
        filters = request.filters.model_dump(exclude_none=True)

    user_content = f"Query: {request.query}"
    if filters:
        user_content += f"\nFilters: {json.dumps(filters)}"

    # Standard OpenAI messages list: system prompt + user message, then tool results appended.
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    max_turns = get_settings().agent_max_turns
    log.info("agent.start", query=request.query, filters=filters, max_turns=max_turns)
    # Tracks whether any search produced data. Gates finalize_notice: the agent may
    # only decline with a "no data" notice when nothing chartable exists — a query
    # that returned trials can never be declined.
    had_results = False
    for _turn in range(max_turns):
        log.info("agent.turn", turn=_turn + 1, max_turns=max_turns)
        message = provider.complete(messages, TOOLS)
        # Append the assistant message first — OpenAI requires tool results to follow
        # the assistant message that issued the tool calls.
        messages.append(message)

        if not message.tool_calls:
            raise ValueError("Agent produced no tool calls.")

        result: VisualizationResponse | None = None

        for tc in message.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            fn = TOOL_FNS.get(fn_name)

            log.info("tool.call", name=fn_name, arguments=fn_args)
            if fn is None:
                tool_result: Any = {"error": f"Unknown tool: {fn_name}"}
            else:
                # Guard execution: bad arguments (extra keys, invalid enum values) or
                # any runtime failure become an error result fed back to the model so it
                # can self-correct on the next turn, rather than 500-ing the request.
                try:
                    tool_result = fn(**fn_args)
                except Exception as exc:
                    log.warning("tool.error", name=fn_name, error=str(exc), exc_info=True)
                    tool_result = {"error": f"{type(exc).__name__}: {exc}"}

            # A search that returns a dataset_id means chartable data exists.
            if fn_name == "search_trials" and isinstance(tool_result, dict) and tool_result.get("dataset_id"):
                had_results = True

            if fn_name in _TERMINAL_TOOLS and isinstance(tool_result, VisualizationResponse):
                if fn_name == "finalize_notice" and had_results:
                    # Code gate: refuse to decline when data exists; force a real chart.
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({
                            "error": "Matching trials were found; produce a visualization "
                                     "with finalize_visualization. Do not decline."
                        }),
                    })
                else:
                    # Terminal success — exit the loop immediately.
                    result = tool_result
            elif fn_name in _TERMINAL_TOOLS:
                # Terminal tool returned a dict (e.g. bad result_id) — feed the error
                # back so the agent can retry with corrected arguments.
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result, default=str),
                })
            else:
                # Regular tool — append result so the agent can read it on the next turn.
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result, default=str),
                })

        if result is not None:
            return result

    # Turn limit reached. If no search ever found data, this is a genuine "no data"
    # outcome — return a clean notice rather than raising (which would 500 the request).
    if not had_results:
        log.info("agent.no_data_fallback")
        return finalize_notice(_NO_DATA_MESSAGE)
    raise ValueError("Agent did not call finalize_visualization within the turn limit.")
