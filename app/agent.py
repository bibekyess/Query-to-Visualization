"""
OpenAI tool-calling agent.

The agent's only job is language and control flow:
  1. Decide which search parameters to use.
  2. Decide whether to aggregate or build a network.
  3. Provide a human-readable title and axis labels.

Everything numeric stays in Python (tools.py). The agent only passes UUIDs
(dataset_id, result_id) and string field names between tool calls.
"""
from __future__ import annotations
import json
import os
from typing import Any
from openai import OpenAI
from app import tools as T
from app.models import QueryRequest, VisualizationResponse

# Lazy init: creating OpenAI() at import time raises KeyError if OPENAI_API_KEY is not set,
# which breaks `from app.api import app` in tests or CI that don't have a key loaded yet.
_client: OpenAI | None = None
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


# The system prompt is the agent's complete instruction set. It must be explicit about:
# - The exact workflow order (search → aggregate|network → finalize)
# - When to use each group_by value
# - The encoding convention so axis field names match the data dict keys
# - The no-numbers rule (the most important anti-hallucination constraint)
SYSTEM_PROMPT = """\
You are a clinical trials data analyst agent. You answer questions about clinical
trials by fetching real data from ClinicalTrials.gov and returning a structured
visualization specification.

## Workflow (always follow this order)
1. Call `search_trials` with the user's query parameters.
2. If total_count = 0, retry with a broader `query_term` (drop specific filters).
3. Call `aggregate` OR `build_network` depending on the question.
4. Call `finalize_visualization` — this is always your last action.

## Choosing `group_by` for `aggregate`
| User intent                            | group_by          |
|----------------------------------------|-------------------|
| Trend over time (multi-year span)      | start_year        |
| Trend over time (≤ 2-year span)        | start_month       |
| Phase distribution                     | phase             |
| Geographic / by country                | country           |
| By sponsor organization                | sponsor_name      |
| By sponsor type (industry vs academic) | sponsor_class     |
| Enrollment status breakdown            | status            |
| Intervention type breakdown            | intervention_type |
| Study type breakdown                   | study_type        |
| Most common conditions                 | condition         |
| Enrollment size distribution           | enrollment_bucket |

## When to call `build_network` instead
Use `build_network` when the query asks for:
- "network of…", "relationships between…", "co-occurrence of…"
- "which drugs co-occur…", "sponsor-drug network…"
- node_type options: condition | intervention | sponsor | country

## Choosing `viz_hint` for `finalize_visualization`
- Time trend → "time_series"
- Enrollment size distribution → "histogram"
- 2-variable comparison → "scatter"
- Relationship network → "network_graph"
- Default distribution → omit (system chooses bar_chart)

## Encoding rules
The `encoding` dict maps visual channels to field names in the data:
- For bar/time charts: {"x": "<group_by field>", "y": "count"}
- For network: leave encoding as {} — the system fills it in automatically.
Always match the encoding field names exactly to what `group_by` produced.

## Critical rules
- NEVER invent numbers, trial names, or dates. All values come from tool outputs.
- NEVER modify or summarise numeric data — pass result_id through unchanged.
- Keep titles under 80 characters, human-readable.
- Always call `finalize_visualization` as your very last tool call.
"""

# OpenAI function-calling schemas for each tool.
# The "description" fields are what the model reads to understand each parameter;
# they must be precise enough that the model won't misuse them.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_trials",
            "description": (
                "Fetch matching clinical trials from ClinicalTrials.gov and cache them. "
                "Returns dataset_id for use in subsequent tools, total_count, and sample titles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query_term": {
                        "type": "string",
                        "description": "General full-text search fallback (used when condition/intervention not set)",
                    },
                    "condition": {
                        "type": "string",
                        "description": "Disease or condition, e.g. 'diabetes', 'breast cancer'",
                    },
                    "intervention": {
                        "type": "string",
                        "description": "Drug or intervention name, e.g. 'pembrolizumab'",
                    },
                    "sponsor": {"type": "string", "description": "Sponsor or organization name"},
                    "phases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Phase filter list, e.g. ['3'] or ['1', '2']",
                    },
                    "start_year": {
                        "type": "integer",
                        "description": "Include only studies starting from this year",
                    },
                    "end_year": {
                        "type": "integer",
                        "description": "Include only studies starting up to and including this year",
                    },
                    "country": {"type": "string", "description": "Country name filter"},
                    "status": {
                        "type": "string",
                        "description": "Trial status filter, e.g. RECRUITING, COMPLETED",
                    },
                    "max_records": {
                        "type": "integer",
                        "description": "Max records to fetch (default 5000; increase for broader coverage)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate",
            "description": (
                "Group fetched studies by a field and count them. "
                "Returns result_id and group labels. "
                "Numbers stay in Python — you will NOT see raw counts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "dataset_id from search_trials",
                    },
                    "group_by": {
                        "type": "string",
                        "enum": [
                            "phase", "status", "start_year", "start_month",
                            "completion_year", "sponsor_name", "sponsor_class",
                            "country", "intervention_type", "study_type",
                            "condition", "enrollment_bucket",
                        ],
                        "description": "Field to group studies by",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Max groups to return (default 20)",
                    },
                },
                "required": ["dataset_id", "group_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_network",
            "description": (
                "Build a co-occurrence network from fetched studies. "
                "Returns result_id, node count, and top node labels."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "dataset_id from search_trials",
                    },
                    "node_type": {
                        "type": "string",
                        "enum": ["condition", "intervention", "sponsor", "country"],
                        "description": "Entity type for network nodes",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Max nodes to include (default 25)",
                    },
                },
                "required": ["dataset_id", "node_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize_visualization",
            "description": (
                "Assemble and return the final visualization specification. "
                "MUST be your last tool call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "result_id": {
                        "type": "string",
                        "description": "result_id from aggregate or build_network",
                    },
                    "title": {
                        "type": "string",
                        "description": "Human-readable chart title (under 80 chars)",
                    },
                    "encoding": {
                        "type": "object",
                        "description": (
                            "Visual channel → field mapping. "
                            "For bar/line: {\"x\": \"<group_by>\", \"y\": \"count\"}. "
                            "For network: {} (auto-set)."
                        ),
                        "properties": {
                            "x": {"type": "string"},
                            "y": {"type": "string"},
                            "series": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                    "viz_hint": {
                        "type": "string",
                        "enum": [
                            "bar_chart", "time_series", "histogram",
                            "scatter", "network_graph", "grouped_bar",
                        ],
                        "description": "Optional viz type override",
                    },
                },
                "required": ["result_id", "title", "encoding"],
            },
        },
    },
]

# Maps tool name strings (from the LLM's response) to the actual Python functions.
_TOOL_FNS = {
    "search_trials": T.search_trials,
    "aggregate": T.aggregate,
    "build_network": T.build_network,
    "finalize_visualization": T.finalize_visualization,
}


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

    client = _get_client()

    # tool_choice="required" forces a tool call every turn, preventing the model from
    # responding with plain text ("I need more information…") instead of calling a tool.
    for _turn in range(12):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="required",
        )
        choice = response.choices[0]
        # Append the assistant message first — OpenAI requires tool results to follow
        # the assistant message that issued the tool calls.
        messages.append(choice.message)

        if not choice.message.tool_calls:
            raise ValueError("Agent produced no tool calls.")

        result: VisualizationResponse | None = None

        for tc in choice.message.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            fn = _TOOL_FNS.get(fn_name)

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
