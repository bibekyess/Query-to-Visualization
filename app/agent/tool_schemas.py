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
            "name": "aggregate_comparison",
            "description": (
                "Compare two or more datasets side by side on a shared field "
                "(e.g. 'Drug A vs Drug B by phase', 'two conditions over time'). "
                "First call search_trials once per item to get a dataset_id, then pass "
                "them here with human-readable labels. Returns result_id, group labels, "
                "and series labels — numbers stay in Python. Produces a grouped_bar "
                "(or multi-series time_series for date fields)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "series": {
                        "type": "array",
                        "minItems": 2,
                        "items": {
                            "type": "object",
                            "properties": {
                                "dataset_id": {
                                    "type": "string",
                                    "description": "dataset_id from a search_trials call",
                                },
                                "label": {
                                    "type": "string",
                                    "description": "Series name, e.g. 'Pembrolizumab' or 'Diabetes'",
                                },
                            },
                            "required": ["dataset_id", "label"],
                            "additionalProperties": False,
                        },
                        "description": "Two or more datasets to compare, each with a display label",
                    },
                    "group_by": {
                        "type": "string",
                        "enum": [
                            "phase", "status", "start_year", "start_month",
                            "completion_year", "sponsor_name", "sponsor_class",
                            "country", "intervention_type", "study_type",
                            "condition", "enrollment_bucket",
                        ],
                        "description": "Shared field to group each series by (same axis for all series)",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Max groups on the shared axis (default 20)",
                    },
                },
                "required": ["series", "group_by"],
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
            "name": "scatter_points",
            "description": (
                "Build a scatter plot from TWO continuous per-trial variables "
                "(e.g. 'enrollment vs trial duration', 'enrollment vs start year'). "
                "One point per trial that has both values. Returns result_id and a "
                "point count — coordinates stay in Python."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "dataset_id from search_trials",
                    },
                    "x_field": {
                        "type": "string",
                        "enum": ["enrollment", "duration_days", "start_year"],
                        "description": "Continuous variable for the x-axis",
                    },
                    "y_field": {
                        "type": "string",
                        "enum": ["enrollment", "duration_days", "start_year"],
                        "description": "Continuous variable for the y-axis",
                    },
                    "max_points": {
                        "type": "integer",
                        "description": "Max points to plot (default 500)",
                    },
                },
                "required": ["dataset_id", "x_field", "y_field"],
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
                        "enum": ["bar_chart", "time_series", "histogram"],
                        "description": (
                            "Optional chart-type override for an aggregate result. "
                            "Time fields auto-select time_series and enrollment auto-selects "
                            "histogram regardless of this hint; networks are set automatically."
                        ),
                    },
                },
                "required": ["result_id", "title", "encoding"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize_notice",
            "description": (
                "Terminal fallback when NO matching trials were found, even after "
                "broadening the search. Returns a 'no data' message instead of a chart. "
                "Use ONLY when every search returned 0 results — never when any search "
                "returned data (always visualize data that exists)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": (
                            "Short human-readable explanation, e.g. 'No clinical trials "
                            "matched these criteria; try broadening the query.'"
                        ),
                    },
                },
                "required": ["message"],
            },
        },
    },
]
