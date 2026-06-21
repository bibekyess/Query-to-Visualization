"""Tool 2: aggregate — group fetched studies by a field and count them in Python."""
from __future__ import annotations

import uuid
from collections import defaultdict

from app.clinicaltrials import extractors as ct
from app.tools.store import AGG_RESULTS, DATASETS

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
