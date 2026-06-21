"""
Four agent tools. All numeric aggregation happens here in Python — the LLM
never sees or types data values, only result_ids and field name labels.

Data flow:
  search_trials() → stores raw studies → returns dataset_id
  aggregate()     → reads DATASETS[dataset_id] → stores bucketed data → returns result_id
  build_network() → reads DATASETS[dataset_id] → stores graph data   → returns result_id
  finalize_visualization() → reads AGG_RESULTS or NET_RESULTS → builds the API response
"""
from __future__ import annotations
import uuid
from collections import defaultdict, Counter
from typing import Any

from app import ct_client as ct
from app.models import (
    Citation, NetworkNode, NetworkEdge,
    Visualization, ResponseMetadata, VisualizationResponse,
)
from app.viz_selector import select as select_viz_type

# --- In-memory state ---
# Keys are UUID strings generated at fetch time; values are the raw study dicts from the API.
# No TTL or eviction — this is intentionally simple for a demo/take-home context.
DATASETS: dict[str, list[dict]] = {}
DATASET_META: dict[str, dict] = {}   # total_count, fetched_count, query_params per dataset
AGG_RESULTS: dict[str, dict] = {}    # bucketed data + citations, keyed by result_id
NET_RESULTS: dict[str, dict] = {}    # graph nodes + edges, keyed by result_id


# ─────────────────────────────────────────────
# Tool 1: search_trials
# ─────────────────────────────────────────────

def search_trials(
    query_term: str | None = None,
    condition: str | None = None,
    intervention: str | None = None,
    sponsor: str | None = None,
    phases: list[str] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    country: str | None = None,
    status: str | None = None,
    max_records: int = 5000,
) -> dict:
    """
    Fetch studies from ClinicalTrials.gov and cache them.
    Returns dataset_id (for subsequent tools), total_count, and sample titles.
    """
    params: dict[str, str] = {}

    # The API provides separate search slots for condition and intervention; using them
    # gives more precise results than dumping everything into query.term.
    if condition:
        params["query.cond"] = condition
    if intervention:
        params["query.intr"] = intervention
    if sponsor:
        params["query.spons"] = sponsor
    # query.term is a general full-text fallback; only use it when the specific fields are absent
    # to avoid double-counting (condition AND term would over-narrow the results).
    if query_term and not (condition or intervention):
        params["query.term"] = query_term
    if status:
        params["filter.overallStatus"] = status.upper()

    # Phase, date range, and country filters don't have dedicated params; they must be
    # expressed as Essie expressions in filter.advanced (verified in API investigation).
    essie = ct.build_essie(phases, start_year, end_year, country)
    if essie:
        params["filter.advanced"] = essie

    if not params:
        params["query.term"] = query_term or "clinical trial"

    # Count first (cheap: one request, pageSize=1) so we can bail early on zero results
    # and later verify our aggregation against the authoritative server total.
    total_count = ct.count_studies(params)

    if total_count == 0:
        return {
            "dataset_id": None,
            "total_count": 0,
            "fetched_count": 0,
            "sample_titles": [],
            "error": "No studies found. Try broader search terms.",
        }

    # Hard cap at 10 000 to prevent runaway fetches on very broad queries.
    capped = min(max_records, 10_000)
    studies = ct.fetch_all_studies(params, max_records=capped)

    dataset_id = str(uuid.uuid4())
    DATASETS[dataset_id] = studies
    DATASET_META[dataset_id] = {
        "total_count": total_count,
        "fetched_count": len(studies),
        "query_params": params,
    }

    return {
        "dataset_id": dataset_id,
        "total_count": total_count,
        "fetched_count": len(studies),
        # Sample titles let the LLM confirm it fetched the right studies before aggregating.
        "sample_titles": [ct.extract_brief_title(s) for s in studies[:5]],
        "warning": (
            f"Fetched {len(studies)} of {total_count} total — some records omitted."
            if total_count > len(studies) else None
        ),
    }


# ─────────────────────────────────────────────
# Tool 2: aggregate
# ─────────────────────────────────────────────

# Human-readable labels for the API's ALL_CAPS phase enum values.
_PHASE_DISPLAY: dict[str, str] = {
    "EARLY_PHASE1": "Early Phase 1",
    "PHASE1": "Phase 1",
    "PHASE2": "Phase 2",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NA": "N/A",
}


def _enrollment_bucket(count: int | None) -> str:
    # Fixed bucket boundaries chosen to be meaningful for clinical trial sizes.
    if count is None:
        return "Unknown"
    if count < 50:
        return "< 50"
    if count < 200:
        return "50–199"
    if count < 1_000:
        return "200–999"
    if count < 5_000:
        return "1,000–4,999"
    return "5,000+"


def _study_groups(study: dict, group_by: str) -> list[str]:
    """
    Return the group label(s) this study belongs to for a given group_by field.

    Returns a LIST because some fields are multi-valued:
    - A study can be listed under Phase 1 AND Phase 2 (Phase 1/2 trials).
    - A study can have sites in many countries.
    - A study can target multiple conditions.
    When a study maps to multiple groups, it is counted once per group — this inflates
    the total-grouped count above fetched_count, which is intentional and documented.
    """
    if group_by == "phase":
        phases = ct.extract_phases(study)
        return [_PHASE_DISPLAY.get(p, p) for p in phases] if phases else ["N/A"]
    if group_by == "status":
        return [ct.extract_status(study)]
    if group_by == "start_year":
        d = ct.extract_start_date(study)
        return [d[:4]] if d and len(d) >= 4 else ["Unknown"]
    if group_by == "start_month":
        d = ct.extract_start_date(study)
        # Slice to YYYY-MM; ISO format means lexicographic sort == chronological sort.
        return [d[:7]] if d and len(d) >= 7 else ["Unknown"]
    if group_by == "completion_year":
        d = ct.extract_completion_date(study)
        return [d[:4]] if d and len(d) >= 4 else ["Unknown"]
    if group_by == "sponsor_name":
        return [ct.extract_sponsor_name(study)]
    if group_by == "sponsor_class":
        return [ct.extract_sponsor_class(study)]
    if group_by == "country":
        countries = ct.extract_countries(study)
        return countries if countries else ["Unknown"]
    if group_by == "intervention_type":
        types = ct.extract_intervention_types(study)
        return types if types else ["OTHER"]
    if group_by == "study_type":
        return [ct.extract_study_type(study)]
    if group_by == "condition":
        conds = ct.extract_conditions(study)
        # Cap at 3 per study to avoid high-condition studies dominating the distribution.
        return conds[:3] if conds else ["Unknown"]
    if group_by == "enrollment_bucket":
        return [_enrollment_bucket(ct.extract_enrollment(study))]
    return ["Unknown"]


def aggregate(
    dataset_id: str,
    group_by: str,
    top_n: int = 20,
) -> dict:
    """
    Group fetched studies by a field and count them.

    Critically, this returns only group LABELS to the LLM — not the counts.
    The counts are stored in AGG_RESULTS and only retrieved in finalize_visualization.
    This prevents the LLM from ever writing numeric data into the output.
    """
    if dataset_id not in DATASETS:
        return {"error": f"Dataset {dataset_id!r} not found. Call search_trials first."}

    studies = DATASETS[dataset_id]
    counts: dict[str, int] = defaultdict(int)
    # Collect citations as we count, so we don't need a second pass over the studies later.
    citations_map: dict[str, list[dict]] = defaultdict(list)

    for study in studies:
        nct_id = ct.extract_nct_id(study)
        excerpt = ct.extract_brief_summary(study)[:200]
        for group in _study_groups(study, group_by):
            counts[group] += 1
            # Cap at 3 citations per group to keep the response payload manageable.
            if len(citations_map[group]) < 3:
                citations_map[group].append({"nct_id": nct_id, "excerpt": excerpt})

    sorted_groups = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_n]

    # Store the full bucketed data (including counts) server-side, keyed by result_id.
    # The LLM only receives the label list; numbers never enter the LLM context.
    data = [
        {group_by: label, "count": count, "citations": citations_map[label]}
        for label, count in sorted_groups
    ]

    result_id = str(uuid.uuid4())
    AGG_RESULTS[result_id] = {
        "data": data,
        "group_by": group_by,
        "dataset_id": dataset_id,
    }

    return {
        "result_id": result_id,
        "groups": [g for g, _ in sorted_groups],   # labels only, no counts
        "num_groups": len(sorted_groups),
    }


# ─────────────────────────────────────────────
# Tool 3: build_network
# ─────────────────────────────────────────────

def _network_entities(study: dict, node_type: str) -> list[str]:
    # Returns entity names for a single study; these become network nodes.
    if node_type == "condition":
        return ct.extract_conditions(study)[:5]
    if node_type == "intervention":
        return [iv.get("name", "") for iv in ct.extract_interventions(study) if iv.get("name")][:5]
    if node_type == "sponsor":
        return [ct.extract_sponsor_name(study)]
    if node_type == "country":
        return ct.extract_countries(study)
    return []


def build_network(
    dataset_id: str,
    node_type: str = "condition",
    top_n: int = 25,
) -> dict:
    """
    Build a co-occurrence network: two entities are connected if they appear
    in the same study. Edge weight = number of studies they share.
    """
    if dataset_id not in DATASETS:
        return {"error": f"Dataset {dataset_id!r} not found. Call search_trials first."}

    studies = DATASETS[dataset_id]
    node_counts: Counter[str] = Counter()
    edge_counts: Counter[tuple[str, str]] = Counter()

    for study in studies:
        # Deduplicate within a study (a study shouldn't create self-loops or duplicate edges).
        # Cap at 10 to prevent combinatorial explosion on studies with many entities
        # (10 entities → at most 45 pairs; without the cap one study could generate thousands).
        entities = list(set(_network_entities(study, node_type)))[:10]
        for e in entities:
            node_counts[e] += 1
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                # Sort the pair so (A, B) and (B, A) map to the same counter key.
                a, b = sorted([entities[i], entities[j]])
                edge_counts[(a, b)] += 1

    # Keep only the most-mentioned nodes; everything else would be noise in a visualisation.
    top_nodes = [n for n, _ in node_counts.most_common(top_n)]
    top_set = set(top_nodes)

    nodes = [{"id": n, "label": n, "weight": node_counts[n]} for n in top_nodes]
    # Keep only edges whose both endpoints made the top-N cut, then cap total edges.
    edges = [
        {"source": a, "target": b, "weight": w}
        for (a, b), w in sorted(edge_counts.items(), key=lambda x: x[1], reverse=True)
        if a in top_set and b in top_set
    ][:150]

    result_id = str(uuid.uuid4())
    NET_RESULTS[result_id] = {
        "nodes": nodes,
        "edges": edges,
        "node_type": node_type,
        "dataset_id": dataset_id,
        "truncated": len(node_counts) > top_n,
        "total_nodes": len(node_counts),
    }

    return {
        "result_id": result_id,
        "num_nodes": len(nodes),
        "num_edges": len(edges),
        "top_node_labels": [n["label"] for n in nodes[:5]],
        "truncated": len(node_counts) > top_n,
        "total_nodes_in_data": len(node_counts),
    }


# ─────────────────────────────────────────────
# Tool 4: finalize_visualization  (terminal)
# ─────────────────────────────────────────────

def finalize_visualization(
    result_id: str,
    title: str,
    encoding: dict[str, str],
    viz_hint: str | None = None,
) -> VisualizationResponse | dict:
    """
    Assemble the final visualization spec from a stored aggregate or network result.

    Returns VisualizationResponse on success, or a plain dict with "error" on failure.
    The agent loop in agent.py checks the return type: a VisualizationResponse terminates
    the loop and becomes the API response; a dict is fed back to the LLM to recover.
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
    # When False, the aggregation is over a sample and the server total is shown separately.
    count_verified = total_count == fetched_count

    # Expose the query params that were actually sent to the API so the response is auditable.
    filters = {k: v for k, v in (meta.get("query_params") or {}).items()}
    filters["source"] = "clinicaltrials.gov"

    warnings: list[str] = []
    if total_count > fetched_count:
        warnings.append(
            f"Results truncated: {fetched_count:,} of {total_count:,} studies fetched. "
            "Aggregation reflects fetched subset."
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
            query_interpretation=(
                f"Co-occurrence network of {node_type}s across {fetched:,} studies"
            ),
            warnings=warnings,
        ),
    )
