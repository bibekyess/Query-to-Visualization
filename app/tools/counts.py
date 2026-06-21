"""
Exact per-group counts via server-side countTotal queries.

When a result set is larger than what we fetch (truncated), aggregating the
fetched sample gives a biased distribution — the sample is the first N records
in the API's default order, not a random draw. For fields whose values are
enumerable (fixed enums, fixed buckets, or a bounded date span), we instead ask
the server for the exact count of each bucket with one cheap
`countTotal=true&pageSize=1` request per bucket. Counts are then authoritative
regardless of corpus size, while citations still come from the fetched sample.

Returns None for unbounded fields (sponsor_name, condition, country): their
value space is too large to enumerate cheaply, so the caller keeps the
sample-based counts and flags them as approximate.

Bucket LABELS here must match exactly what tools/aggregate._study_groups emits
for the same field, so the per-bucket citations collected from the sample line
up with the exact counts.
"""
from __future__ import annotations

from app.clinicaltrials import client

# Phase: display labels (matching aggregate._PHASE_DISPLAY) → Essie clause.
_PHASE_CLAUSES: dict[str, str] = {
    "Early Phase 1": "AREA[Phase]EARLY_PHASE1",
    "Phase 1": "AREA[Phase]PHASE1",
    "Phase 2": "AREA[Phase]PHASE2",
    "Phase 3": "AREA[Phase]PHASE3",
    "Phase 4": "AREA[Phase]PHASE4",
    "N/A": "AREA[Phase]NA",
}

# For these fields the bucket label IS the raw API enum value, so the clause is
# built as AREA[<Field>]<label>. (Verified field names; see API investigation.)
_ENUM_FIELDS: dict[str, tuple[str, list[str]]] = {
    "status": ("OverallStatus", [
        "RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION",
        "ACTIVE_NOT_RECRUITING", "SUSPENDED", "TERMINATED", "COMPLETED",
        "WITHDRAWN", "UNKNOWN",
    ]),
    "sponsor_class": ("LeadSponsorClass", [
        "INDUSTRY", "OTHER", "FED", "NIH", "NETWORK", "OTHER_GOV", "INDIV", "UNKNOWN",
    ]),
    "intervention_type": ("InterventionType", [
        "DRUG", "BIOLOGICAL", "DEVICE", "PROCEDURE", "RADIATION", "BEHAVIORAL",
        "DIETARY_SUPPLEMENT", "GENETIC", "DIAGNOSTIC_TEST", "COMBINATION_PRODUCT", "OTHER",
    ]),
    "study_type": ("StudyType", ["INTERVENTIONAL", "OBSERVATIONAL", "EXPANDED_ACCESS"]),
}

# Enrollment buckets: label (matching aggregate._enrollment_bucket) → range clause.
# "Unknown" (no enrollment value) is derived as total - sum(numeric buckets).
_ENROLLMENT_BUCKETS: list[tuple[str, str]] = [
    ("< 50", "AREA[EnrollmentCount]RANGE[MIN,49]"),
    ("50–199", "AREA[EnrollmentCount]RANGE[50,199]"),
    ("200–999", "AREA[EnrollmentCount]RANGE[200,999]"),
    ("1,000–4,999", "AREA[EnrollmentCount]RANGE[1000,4999]"),
    ("5,000+", "AREA[EnrollmentCount]RANGE[5000,MAX]"),
]

# group_by → Essie date field, for year-bucketed time series.
_DATE_AREAS: dict[str, str] = {
    "start_year": "StartDate",
    "completion_year": "CompletionDate",
}

# Guard against firing hundreds of requests on a very wide span.
_MAX_DATE_BUCKETS = 40


def supports_exact(group_by: str) -> bool:
    """True when this field's buckets can be counted exactly server-side."""
    return (
        group_by == "phase"
        or group_by in _ENUM_FIELDS
        or group_by == "enrollment_bucket"
        or group_by in _DATE_AREAS
    )


def exact_counts(group_by: str, base_params: dict, total_count: int) -> dict[str, int] | None:
    """
    Compute exact per-bucket counts for `group_by` over the scoped query.

    Returns {label: count} (zero-count buckets dropped), or None when the field
    is not exactly countable (caller falls back to the sample).
    """
    if group_by == "phase":
        return _count_clauses(base_params, _PHASE_CLAUSES)

    if group_by in _ENUM_FIELDS:
        area, values = _ENUM_FIELDS[group_by]
        return _count_clauses(base_params, {v: f"AREA[{area}]{v}" for v in values})

    if group_by == "enrollment_bucket":
        return _count_enrollment(base_params, total_count)

    if group_by in _DATE_AREAS:
        return _count_years(base_params, _DATE_AREAS[group_by])

    return None


def _count_clauses(base_params: dict, label_to_clause: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label, clause in label_to_clause.items():
        c = client.count_with_clause(base_params, clause)
        if c:  # drop empty buckets so the chart isn't padded with zeros
            counts[label] = c
    return counts


def _count_enrollment(base_params: dict, total_count: int) -> dict[str, int]:
    counts = _count_clauses(base_params, dict(_ENROLLMENT_BUCKETS))
    # Studies with no enrollment value fall in none of the numeric ranges.
    unknown = total_count - sum(counts.values())
    if unknown > 0:
        counts["Unknown"] = unknown
    return counts


def _count_years(base_params: dict, area: str) -> dict[str, int] | None:
    lo, hi = client.date_bounds(base_params, area)
    if lo is None or hi is None or (hi - lo) >= _MAX_DATE_BUCKETS:
        return None  # no usable dates, or span too wide → fall back to sample
    counts: dict[str, int] = {}
    for year in range(lo, hi + 1):
        clause = f"AREA[{area}]RANGE[{year}-01-01,{year}-12-31]"
        c = client.count_with_clause(base_params, clause)
        if c:
            counts[str(year)] = c
    return counts
