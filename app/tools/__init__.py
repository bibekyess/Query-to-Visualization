"""
Agent tools.

The four functions the LLM can call. All numeric aggregation happens here in
Python — the LLM never sees or types data values, only opaque dataset_id /
result_id handles and field-name labels.

Data flow:
  search_trials() → stores raw studies → returns dataset_id
  aggregate()     → reads store → stores bucketed data → returns result_id
  build_network() → reads store → stores graph data   → returns result_id
  finalize_visualization() → reads stored result → builds the API response
"""
from app.tools.aggregate import aggregate
from app.tools.finalize import finalize_visualization
from app.tools.network import build_network
from app.tools.search import search_trials

__all__ = ["search_trials", "aggregate", "build_network", "finalize_visualization"]
