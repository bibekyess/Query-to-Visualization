"""
Streaming chat providers — OpenAI and Anthropic behind one interface.

The chat agent loop is provider-agnostic. Each provider:
  - owns its native message-list format (built from a neutral text-only history),
  - streams one assistant turn, yielding {"type": "text", "text": ...} deltas,
    then a final {"type": "turn_end", "turn": TurnResult},
  - knows how to append the assistant turn and tool results back onto its
    native message list so the loop can continue.

Tools are declared once in a neutral shape:
    {"name": ..., "description": ..., "input_schema": {<JSON Schema>}}
which is Anthropic's native format; the OpenAI adapter wraps it into the
OpenAI "function" envelope.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class TurnResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Provider-native assistant payload, appended back verbatim on the next turn.
    # For Anthropic this carries thinking/tool_use blocks that MUST round-trip unchanged.
    raw_assistant: Any = None


class OpenAIChatProvider:
    """Chat Completions with streaming + tool calls."""

    def __init__(self) -> None:
        from openai import OpenAI  # local import: only needed when this provider is active
        settings = get_settings()
        self.client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
        self.model = settings.openai_model
        self.max_tokens = settings.chat_max_tokens

    def build_messages(self, system: str, history: list[dict], user_message: str) -> list:
        messages: list[dict] = [{"role": "system", "content": system}]
        messages.extend({"role": m["role"], "content": m["content"]} for m in history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def stream_turn(self, messages: list, tools: list[dict]) -> Iterator[dict]:
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=[
                {"type": "function", "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                }}
                for t in tools
            ],
            max_tokens=self.max_tokens,
            stream=True,
        )

        text_parts: list[str] = []
        # Tool-call fragments arrive as deltas keyed by index; accumulate then parse.
        pending: dict[int, dict] = {}
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                text_parts.append(delta.content)
                yield {"type": "text", "text": delta.content}
            for tc in delta.tool_calls or []:
                slot = pending.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["arguments"] += tc.function.arguments

        tool_calls = []
        for idx in sorted(pending):
            slot = pending[idx]
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=slot["id"], name=slot["name"], arguments=args))

        raw_assistant = {
            "role": "assistant",
            "content": "".join(text_parts) or None,
        }
        if tool_calls:
            raw_assistant["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in tool_calls
            ]
        yield {"type": "turn_end",
               "turn": TurnResult("".join(text_parts), tool_calls, raw_assistant)}

    def append_assistant_turn(self, messages: list, turn: TurnResult) -> None:
        messages.append(turn.raw_assistant)

    def append_tool_results(self, messages: list, results: list[tuple[ToolCall, str]]) -> None:
        for tc, content in results:
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})


class AnthropicChatProvider:
    """Anthropic Messages API with streaming + tool use (adaptive thinking)."""

    def __init__(self) -> None:
        import anthropic  # local import: only needed when this provider is active
        settings = get_settings()
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
        self.model = settings.anthropic_model
        self.max_tokens = settings.chat_max_tokens
        self.system = ""

    def build_messages(self, system: str, history: list[dict], user_message: str) -> list:
        # Anthropic takes the system prompt as a request parameter, not a message.
        self.system = system
        messages = [{"role": m["role"], "content": m["content"]} for m in history]
        messages.append({"role": "user", "content": user_message})
        return messages

    def stream_turn(self, messages: list, tools: list[dict]) -> Iterator[dict]:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system,
            thinking={"type": "adaptive"},
            tools=[
                {"name": t["name"], "description": t["description"],
                 "input_schema": t["input_schema"]}
                for t in tools
            ],
            messages=messages,
        ) as stream:
            for event in stream:
                if (event.type == "content_block_delta"
                        and event.delta.type == "text_delta"
                        and event.delta.text):
                    yield {"type": "text", "text": event.delta.text}
            final = stream.get_final_message()

        if final.stop_reason == "refusal":
            log.warning("chat.anthropic_refusal", stop_details=str(final.stop_details))

        text = "".join(b.text for b in final.content if b.type == "text")
        tool_calls = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
            for b in final.content if b.type == "tool_use"
        ]
        # raw_assistant keeps the full content blocks (thinking included) so they
        # round-trip unchanged on the next request — required for tool-use turns.
        yield {"type": "turn_end", "turn": TurnResult(text, tool_calls, final.content)}

    def append_assistant_turn(self, messages: list, turn: TurnResult) -> None:
        messages.append({"role": "assistant", "content": turn.raw_assistant})

    def append_tool_results(self, messages: list, results: list[tuple[ToolCall, str]]) -> None:
        # All tool results for a turn must land in ONE user message.
        messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tc.id, "content": content}
                for tc, content in results
            ],
        })


def get_chat_provider():
    provider = get_settings().llm_provider.lower()
    if provider == "anthropic":
        return AnthropicChatProvider()
    if provider == "openai":
        return OpenAIChatProvider()
    raise ValueError(f"Unknown LLM_PROVIDER {provider!r}; use 'openai' or 'anthropic'.")
