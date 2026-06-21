"""Maps tool name strings (from the LLM's response) to the actual Python functions."""
from app.tools import (
    aggregate,
    aggregate_comparison,
    build_network,
    finalize_notice,
    finalize_visualization,
    scatter_points,
    search_trials,
)

TOOL_FNS = {
    "search_trials": search_trials,
    "aggregate": aggregate,
    "aggregate_comparison": aggregate_comparison,
    "build_network": build_network,
    "scatter_points": scatter_points,
    "finalize_visualization": finalize_visualization,
    "finalize_notice": finalize_notice,
}
