"""
OpenAI function-calling schemas for the four agent tools.

The "description" fields are what the model reads to understand each parameter;
they must be precise enough that the model won't misuse them.
"""
from app.models import Phase

_PHASE_VALUES = [p.value for p in Phase]

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
                        "items": {
                            "type": "string",
                            "enum": _PHASE_VALUES,
                        },
                        "description": (
                            "Filter to specific trial phase(s); omit for all phases. "
                            "Multiple values are OR-combined, e.g. ['PHASE1', 'PHASE2']. "
                            "Use 'NA' for trials with no applicable phase."
                        ),
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
