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

from app.agent.registry import TOOL_FNS
from app.agent.tool_schemas import TOOLS
from app.config import get_settings
from app.llm import provider
from app.models import QueryRequest, VisualizationResponse
from app.prompts import SYSTEM_PROMPT


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
    for _turn in range(max_turns):
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

            if fn is None:
                tool_result: Any = {"error": f"Unknown tool: {fn_name}"}
            else:
                tool_result = fn(**fn_args)

            if fn_name == "finalize_visualization":
                if isinstance(tool_result, VisualizationResponse):
                    # Success — this is the terminal call; exit the loop immediately.
                    result = tool_result
                else:
                    # finalize failed (bad result_id, etc.) — feed the error back so
                    # the agent can retry with a corrected result_id.
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

    raise ValueError("Agent did not call finalize_visualization within the turn limit.")
