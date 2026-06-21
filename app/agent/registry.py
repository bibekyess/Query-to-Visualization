"""Maps tool name strings (from the LLM's response) to the actual Python functions."""
from app.tools import aggregate, build_network, finalize_visualization, search_trials

TOOL_FNS = {
    "search_trials": search_trials,
    "aggregate": aggregate,
    "build_network": build_network,
    "finalize_visualization": finalize_visualization,
}
