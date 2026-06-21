"""Tool 1: search_trials — fetch matching studies and cache them server-side."""
from __future__ import annotations

import uuid

from app.clinicaltrials import client, extractors, filters
from app.config import get_settings
from app.tools.store import DATASETS, DATASET_META


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
    max_records: int | None = None,
) -> dict:
    """
    Fetch studies from ClinicalTrials.gov and cache them.
    Returns dataset_id (for subsequent tools), total_count, and sample titles.
    """
    settings = get_settings()
    if max_records is None:
        max_records = settings.default_max_records

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
    essie = filters.build_essie(phases, start_year, end_year, country)
    if essie:
        params["filter.advanced"] = essie

    if not params:
        params["query.term"] = query_term or "clinical trial"

    # Count first (cheap: one request, pageSize=1) so we can bail early on zero results
    # and later verify our aggregation against the authoritative server total.
    total_count = client.count_studies(params)

    if total_count == 0:
        return {
            "dataset_id": None,
            "total_count": 0,
            "fetched_count": 0,
            "sample_titles": [],
            "error": "No studies found. Try broader search terms.",
        }

    # Hard cap to prevent runaway fetches on very broad queries.
    capped = min(max_records, settings.max_records_cap)
    studies = client.fetch_all_studies(params, max_records=capped)

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
        "sample_titles": [extractors.extract_brief_title(s) for s in studies[:5]],
        "warning": (
            f"Fetched {len(studies)} of {total_count} total — some records omitted."
            if total_count > len(studies) else None
        ),
    }
