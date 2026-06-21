"""Tool 4: finalize_visualization (terminal) — assemble the final spec from stored results."""
from __future__ import annotations

from typing import Any

from app.models import (
    NetworkEdge,
    NetworkNode,
    ResponseMetadata,
    Visualization,
    VisualizationResponse,
)
from app.tools.store import AGG_RESULTS, DATASET_META, NET_RESULTS
from app.viz import select as select_viz_type


def finalize_visualization(
    result_id: str,
    title: str,
    encoding: dict[str, str],
    viz_hint: str | None = None,
) -> VisualizationResponse | dict:
    """
    Assemble the final visualization spec from a stored aggregate or network result.

    Returns VisualizationResponse on success, or a plain dict with "error" on failure.
    The agent loop checks the return type: a VisualizationResponse terminates the loop
    and becomes the API response; a dict is fed back to the LLM to recover.
    """
    if result_id in AGG_RESULTS:
        return _finalize_agg(result_id, title, encoding, viz_hint)
    if result_id in NET_RESULTS:
        return _finalize_network(result_id, title, encoding)
    return {"error": f"Result {result_id!r} not found. Check result_id from aggregate or build_network."}


def _finalize_agg(
    result_id: str, title: str, encoding: dict[str, str], viz_hint: str | None
) -> VisualizationResponse:
    result = AGG_RESULTS[result_id]
    data = result["data"]
    group_by: str = result["group_by"]
    meta = DATASET_META.get(result["dataset_id"], {})

    viz_type = select_viz_type(group_by, viz_hint)

    # Time-series data must be in chronological order for a line chart to make sense.
    # ISO date strings (YYYY or YYYY-MM) sort correctly with plain string comparison.
    time_granularity: str | None = None
    if group_by == "start_month":
        time_granularity = "month"
        data = sorted(data, key=lambda d: d.get("start_month", ""))
    elif group_by in ("start_year", "completion_year"):
        time_granularity = "year"
        data = sorted(data, key=lambda d: d.get(group_by, ""))

    # If the LLM didn't specify axis fields, fall back to the group_by name and "count".
    x_field = encoding.get("x") or group_by
    y_field = encoding.get("y") or "count"

    enc: dict[str, Any] = {"x": {"field": x_field}, "y": {"field": y_field}}
    if "series" in encoding:
        enc["series"] = {"field": encoding["series"]}

    total_count = meta.get("total_count", 0)
    fetched_count = meta.get("fetched_count", 0)
    # count_verified = True only when we fetched every record (no truncation).
    count_verified = total_count == fetched_count
    # counts_exact = bar values are server-authoritative even if records were truncated
    # (computed via per-group countTotal queries). Set by aggregate().
    counts_exact = result.get("counts_exact", count_verified)

    # Expose the query params that were actually sent to the API so the response is auditable.
    filters = {k: v for k, v in (meta.get("query_params") or {}).items()}
    filters["source"] = "clinicaltrials.gov"

    warnings: list[str] = []
    if total_count > fetched_count and counts_exact:
        # Records were sampled, but the bars themselves are exact server-side counts;
        # only the citation excerpts are drawn from the fetched subset.
        warnings.append(
            f"Bar counts are exact server-side totals over all {total_count:,} studies; "
            f"citation excerpts are sampled from {fetched_count:,} fetched records."
        )
    elif total_count > fetched_count:
        # Unbounded field on a truncated set — counts are an approximation from the sample.
        warnings.append(
            f"Approximate: top groups counted from a {fetched_count:,}-of-{total_count:,} "
            "sample (this field can't be counted exactly server-side). "
            "Proportions may not reflect the full corpus."
        )

    return VisualizationResponse(
        visualization=Visualization(
            type=viz_type,
            title=title,
            encoding=enc,
            data=data,
            filters=filters,
        ),
        response_metadata=ResponseMetadata(
            total_count=total_count,
            fetched_count=fetched_count,
            time_granularity=time_granularity,
            truncated=total_count > fetched_count,
            count_verified=count_verified,
            counts_exact=counts_exact,
            count_server=total_count if not count_verified else None,
            query_interpretation=f"Grouped {fetched_count:,} fetched studies by {group_by!r}",
            warnings=warnings,
        ),
    )


def _finalize_network(
    result_id: str, title: str, encoding: dict[str, str]
) -> VisualizationResponse:
    result = NET_RESULTS[result_id]
    meta = DATASET_META.get(result["dataset_id"], {})
    node_type: str = result["node_type"]

    nodes = [NetworkNode(**n) for n in result["nodes"]]
    edges = [NetworkEdge(**e) for e in result["edges"]]

    filters = {k: v for k, v in (meta.get("query_params") or {}).items()}
    filters["source"] = "clinicaltrials.gov"

    warnings: list[str] = []
    if result.get("truncated"):
        warnings.append(
            f"Network truncated to top 25 nodes ({result['total_nodes']} total). "
            "Increase top_n in build_network to include more."
        )

    fetched = meta.get("fetched_count", 0)

    # count_verified is always False for network results because co-occurrence counts
    # are not comparable to the simple study count from countTotal.
    return VisualizationResponse(
        visualization=Visualization(
            type="network_graph",
            title=title,
            encoding={
                "nodes": {"field": node_type, "weight": "occurrence_count"},
                "edges": {"field": "co_occurrence_weight"},
            },
            nodes=nodes,
            edges=edges,
            filters=filters,
        ),
        response_metadata=ResponseMetadata(
            total_count=meta.get("total_count", 0),
            fetched_count=fetched,
            truncated=result.get("truncated", False),
            count_verified=False,
            counts_exact=False,   # co-occurrence weights are sample-derived, not server counts
            query_interpretation=(
                f"Co-occurrence network of {node_type}s across {fetched:,} studies"
            ),
            warnings=warnings,
        ),
    )
