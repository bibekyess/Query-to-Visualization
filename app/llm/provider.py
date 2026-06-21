"""
OpenAI provider wrapper.

This is the single seam between the agent loop and the LLM SDK. The loop calls
`complete(...)` and gets back one assistant message; it never imports `openai`
directly. To swap providers later, reimplement `complete` against another SDK
and keep the same return shape — nothing else in the codebase changes.
"""
from __future__ import annotations

from typing import Any

from openai import OpenAI

from app.config import get_settings

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
    response = _get_client().chat.completions.create(
        model=get_settings().openai_model,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
    )
    return response.choices[0].message
