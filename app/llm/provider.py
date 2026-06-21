"""
OpenAI provider wrapper.

This is the single seam between the agent loop and the LLM SDK. The loop calls
`complete(...)` and gets back one assistant message; it never imports `openai`
directly. To swap providers later, reimplement `complete` against another SDK
and keep the same return shape — nothing else in the codebase changes.

It is also the single place every LLM call passes through, so it owns the
"we are about to call the model / the model replied" logging.
"""
from __future__ import annotations

from typing import Any

import structlog
from openai import OpenAI

from app.config import get_settings

log = structlog.get_logger(__name__)

# Tool results and the system prompt can be large; previewing keeps the logged
# input readable while still showing what was actually sent.
_PREVIEW_LIMIT = 800


def _preview(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _PREVIEW_LIMIT:
        return value[:_PREVIEW_LIMIT] + f"… [+{len(value) - _PREVIEW_LIMIT} chars]"
    return value


def _summarize_messages(messages: list) -> list[dict]:
    """
    Render the outgoing message list as plain logable dicts.

    The list is a mix of dicts (system/user/tool) and OpenAI message objects
    (the assistant turns the loop appends), so both shapes are handled.
    """
    summary: list[dict] = []
    for m in messages:
        if isinstance(m, dict):
            role, content, tool_calls = m.get("role"), m.get("content"), m.get("tool_calls")
        else:
            role = getattr(m, "role", None)
            content = getattr(m, "content", None)
            tool_calls = getattr(m, "tool_calls", None)

        entry: dict = {"role": role}
        if content:
            entry["content"] = _preview(content)
        if tool_calls:
            entry["tool_calls"] = [
                {"name": tc.function.name, "arguments": _preview(tc.function.arguments)}
                for tc in tool_calls
            ]
        summary.append(entry)
    return summary


# Lazy init: constructing OpenAI() at import time would raise if the API key is
# absent, breaking imports in tests/CI that don't load a key.
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=get_settings().openai_api_key)
    return _client


def complete(
    messages: list[dict],
    tools: list[dict],
    tool_choice: str = "required",
) -> Any:
    """
    Run one chat-completion turn and return the assistant message.

    tool_choice="required" forces a tool call every turn, preventing the model
    from replying with plain text instead of calling a tool.
    """
    model = get_settings().openai_model
    log.info(
        "llm.request",
        model=model,
        tool_choice=tool_choice,
        num_messages=len(messages),
        tools=[t["function"]["name"] for t in tools],
        messages=_summarize_messages(messages),
    )

    response = _get_client().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
    )
    message = response.choices[0].message

    log.info(
        "llm.response",
        model=model,
        finish_reason=response.choices[0].finish_reason,
        tool_calls=[
            {"name": tc.function.name, "arguments": _preview(tc.function.arguments)}
            for tc in (message.tool_calls or [])
        ],
        content=_preview(message.content) if message.content else None,
        usage=response.usage.model_dump() if response.usage else None,
    )
    return message
