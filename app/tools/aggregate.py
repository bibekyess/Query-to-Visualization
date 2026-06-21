"""Tool 2: aggregate — group fetched studies by a field and count them in Python."""
from __future__ import annotations

import uuid
from collections import defaultdict

from app.clinicaltrials import extractors as ct
from app.config import get_settings
from app.tools import counts as exact
from app.tools.store import AGG_RESULTS, DATASETS, DATASET_META

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


# JSON path each citation excerpt is read from, per group_by — so a citation
# actually substantiates the bucket it sits under (not a generic briefSummary).
_SOURCE_FIELD: dict[str, str] = {
    "phase": "protocolSection.designModule.phases",
    "status": "protocolSection.statusModule.overallStatus",
    "start_year": "protocolSection.statusModule.startDateStruct.date",
    "start_month": "protocolSection.statusModule.startDateStruct.date",
    "completion_year": "protocolSection.statusModule.completionDateStruct.date",
    "sponsor_name": "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    "sponsor_class": "protocolSection.sponsorCollaboratorsModule.leadSponsor.class",
    "country": "protocolSection.contactsLocationsModule.locations[].country",
    "intervention_type": "protocolSection.armsInterventionsModule.interventions[].type",
    "study_type": "protocolSection.designModule.studyType",
    "condition": "protocolSection.conditionsModule.conditions[]",
    "enrollment_bucket": "protocolSection.designModule.enrollmentInfo.count",
}


def _citation(study: dict, group_by: str, group: str) -> dict:
    """
    Build one citation that substantiates *this study's membership in `group`*.

    For multi-valued / bucketed fields the excerpt is the specific value that put
    the study in the bucket (the country, the phase, the enrollment count). For
    fields without a tidy single value we fall back to the briefSummary text.
    """
    nct_id = ct.extract_nct_id(study)
    # `group` already is the bucket value for these single-membership fields.
    if group_by in ("country", "intervention_type", "condition", "sponsor_name",
                     "status", "sponsor_class", "study_type"):
        excerpt = group
    elif group_by == "phase":
        excerpt = ", ".join(ct.extract_phases(study)) or "NA"
    elif group_by in ("start_year", "start_month"):
        excerpt = ct.extract_start_date(study) or ""
    elif group_by == "completion_year":
        excerpt = ct.extract_completion_date(study) or ""
    elif group_by == "enrollment_bucket":
        n = ct.extract_enrollment(study)
        excerpt = f"Enrollment: {n}" if n is not None else "Enrollment: unknown"
    else:
        excerpt = ct.extract_brief_summary(study)[:200]
    return {
        "nct_id": nct_id,
        "excerpt": excerpt,
        "source_field": _SOURCE_FIELD.get(group_by, "protocolSection.descriptionModule.briefSummary"),
    }


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


def _compute(
    studies: list[dict],
    meta: dict,
    group_by: str,
    top_n: int,
) -> tuple[list[tuple[str, int]], dict[str, list[dict]], bool]:
    """
    Core per-dataset aggregation, shared by aggregate() and aggregate_comparison().

    Returns (sorted_groups, citations_map, counts_exact):
      - sorted_groups: [(label, count), ...] top_n by count, descending
      - citations_map: label → list of per-bucket citations (from the fetched sample)
      - counts_exact:  True when the bar values are server-authoritative
    """
    total_count: int = meta.get("total_count", len(studies))
    fetched_count: int = meta.get("fetched_count", len(studies))
    truncated = total_count > fetched_count

    # Always tally the fetched sample: it gives per-bucket citations, and serves as
    # the count source whenever exact server-side counts aren't available.
    sample_counts: dict[str, int] = defaultdict(int)
    citations_map: dict[str, list[dict]] = defaultdict(list)
    for study in studies:
        for group in _study_groups(study, group_by):
            sample_counts[group] += 1
            if len(citations_map[group]) < get_settings().citations_per_group:
                citations_map[group].append(_citation(study, group_by, group))

    # Decide where the bar values come from:
    #   - not truncated        → the sample IS the full set, so its counts are exact.
    #   - truncated + countable → ask the server for exact per-bucket counts.
    #   - truncated + unbounded → keep sample counts, flag them as approximate.
    counts: dict[str, int] = sample_counts
    counts_exact = not truncated
    if truncated:
        server_counts = exact.exact_counts(group_by, meta.get("query_params", {}), total_count)
        if server_counts is not None:
            counts = server_counts
            counts_exact = True

    sorted_groups = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return sorted_groups, citations_map, counts_exact


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

    meta = DATASET_META.get(dataset_id, {})
    sorted_groups, citations_map, counts_exact = _compute(
        DATASETS[dataset_id], meta, group_by, top_n
    )

    # Store the full bucketed data (including counts) server-side, keyed by result_id.
    # The LLM only receives the label list; numbers never enter the LLM context.
    data = [
        {group_by: label, "count": count, "citations": citations_map.get(label, [])}
        for label, count in sorted_groups
    ]

    result_id = str(uuid.uuid4())
    AGG_RESULTS[result_id] = {
        "data": data,
        "group_by": group_by,
        "dataset_id": dataset_id,
        "counts_exact": counts_exact,
    }

    return {
        "result_id": result_id,
        "groups": [g for g, _ in sorted_groups],   # labels only, no counts
        "num_groups": len(sorted_groups),
    }


def aggregate_comparison(
    series: list[dict],
    group_by: str,
    top_n: int = 20,
) -> dict:
    """
    Compare two or more datasets side by side on a shared `group_by` field
    (e.g. "Drug A vs Drug B by phase"). Each `series` entry is
    {"dataset_id", "label"}; `label` is the human-readable series name.

    Produces LONG-format rows {group_by, "series", "count", "citations"} — one row
    per (group, series) — which finalize renders as a grouped_bar (or multi-series
    time_series for date fields). Series labels are language supplied by the
    caller; counts and citations stay in Python, so the invariant holds.
    """
    if not series or len(series) < 2:
        return {"error": "aggregate_comparison needs at least 2 series."}

    per_series: list[tuple[str, dict[str, int], dict[str, list[dict]], bool]] = []
    total_count = 0
    fetched_count = 0
    filters: list[dict] = []
    for s in series:
        ds = s.get("dataset_id")
        label = s.get("label") or ds
        if ds not in DATASETS:
            return {"error": f"Dataset {ds!r} not found. Call search_trials first."}
        meta = DATASET_META.get(ds, {})
        # Aggregate each series fully (no per-series cap) so the global top-N ranking is fair.
        sorted_groups, citations_map, exact = _compute(DATASETS[ds], meta, group_by, top_n=10_000)
        per_series.append((label, dict(sorted_groups), citations_map, exact))
        total_count += meta.get("total_count", 0)
        fetched_count += meta.get("fetched_count", 0)
        filters.append({"label": label, "query": meta.get("query_params", {})})

    # Global top group labels by summed count across all series, so every series
    # shows the same x-axis groups (bars align; missing combos get count 0).
    totals: dict[str, int] = defaultdict(int)
    for _, counts, _, _ in per_series:
        for g, c in counts.items():
            totals[g] += c
    top_groups = [g for g, _ in sorted(totals.items(), key=lambda x: x[1], reverse=True)[:top_n]]

    counts_exact = all(exact for *_, exact in per_series)

    data = [
        {
            group_by: g,
            "series": label,
            "count": counts.get(g, 0),
            "citations": citations_map.get(g, []),
        }
        for g in top_groups
        for label, counts, citations_map, _ in per_series
    ]

    result_id = str(uuid.uuid4())
    AGG_RESULTS[result_id] = {
        "data": data,
        "group_by": group_by,
        "dataset_id": series[0].get("dataset_id"),
        "counts_exact": counts_exact,
        "grouped": True,
        "series_field": "series",
        "total_count": total_count,
        "fetched_count": fetched_count,
        "filters": {"comparison": filters},
    }

    return {
        "result_id": result_id,
        "groups": top_groups,
        "series": [label for label, *_ in per_series],   # labels only, no counts
        "num_groups": len(top_groups),
    }
