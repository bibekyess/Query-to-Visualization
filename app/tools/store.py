"""
In-memory state shared across tools.

Keys are UUID strings generated at fetch/aggregate time; values are the raw
study dicts or computed results. No TTL or eviction — this is intentionally
simple for a demo/take-home context (a real deployment would back this with
Redis or SQLite; see README "Limitations").
"""
from __future__ import annotations

DATASETS: dict[str, list[dict]] = {}     # dataset_id → raw study dicts from the API
DATASET_META: dict[str, dict] = {}       # dataset_id → total_count, fetched_count, query_params
AGG_RESULTS: dict[str, dict] = {}        # result_id → bucketed data + citations
NET_RESULTS: dict[str, dict] = {}        # result_id → graph nodes + edges
SCATTER_RESULTS: dict[str, dict] = {}    # result_id → (x, y) points + citations
