"""
Field extractors for ClinicalTrials.gov study records.

All study fields live inside a deeply nested "protocolSection" object.
_get() is a safe path-traversal helper so we never get KeyError on missing fields.
"""
from __future__ import annotations

from typing import Any


def _get(node: Any, *path: str, default: Any = None) -> Any:
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
        if node is None:
            return default
    return node


def extract_nct_id(s: dict) -> str:
    return _get(s, "protocolSection", "identificationModule", "nctId", default="")


def extract_brief_title(s: dict) -> str:
    return _get(s, "protocolSection", "identificationModule", "briefTitle", default="")


def extract_phases(s: dict) -> list[str]:
    # phases is an array (a study can span multiple phases, e.g. Phase 1/2)
    return _get(s, "protocolSection", "designModule", "phases", default=[]) or []


def extract_status(s: dict) -> str:
    return _get(s, "protocolSection", "statusModule", "overallStatus", default="UNKNOWN")


def extract_start_date(s: dict) -> str | None:
    # Date format varies: "YYYY-MM-DD", "YYYY-MM", or "YYYY" — callers slice by length
    return _get(s, "protocolSection", "statusModule", "startDateStruct", "date")


def extract_completion_date(s: dict) -> str | None:
    return _get(s, "protocolSection", "statusModule", "completionDateStruct", "date")


def extract_sponsor_name(s: dict) -> str:
    return _get(s, "protocolSection", "sponsorCollaboratorsModule", "leadSponsor", "name", default="Unknown")


def extract_sponsor_class(s: dict) -> str:
    # class values: INDUSTRY | NIH | FED | NETWORK | OTHER — useful for industry-vs-academic analysis
    return _get(s, "protocolSection", "sponsorCollaboratorsModule", "leadSponsor", "class", default="OTHER")


def extract_conditions(s: dict) -> list[str]:
    # A study can target multiple conditions; returns all of them
    return _get(s, "protocolSection", "conditionsModule", "conditions", default=[]) or []


def extract_interventions(s: dict) -> list[dict]:
    # Each item has {type, name, description}; returns the raw list for callers to filter
    return _get(s, "protocolSection", "armsInterventionsModule", "interventions", default=[]) or []


def extract_countries(s: dict) -> list[str]:
    # A study can have sites in multiple countries; deduplicate while preserving order
    locations = _get(s, "protocolSection", "contactsLocationsModule", "locations", default=[]) or []
    seen: set[str] = set()
    result: list[str] = []
    for loc in locations:
        c = loc.get("country")
        if c and c not in seen:
            seen.add(c)
            result.append(c)
    return result


def extract_enrollment(s: dict) -> int | None:
    count = _get(s, "protocolSection", "designModule", "enrollmentInfo", "count")
    try:
        return int(count) if count is not None else None
    except (ValueError, TypeError):
        return None


def extract_brief_summary(s: dict) -> str:
    # Used as citation excerpt text — free-text description written by the study team
    return _get(s, "protocolSection", "descriptionModule", "briefSummary", default="") or ""


def extract_study_type(s: dict) -> str:
    # Values: INTERVENTIONAL | OBSERVATIONAL | EXPANDED_ACCESS
    return _get(s, "protocolSection", "designModule", "studyType", default="UNKNOWN")


def extract_intervention_types(s: dict) -> list[str]:
    # Deduplicated type labels (e.g. DRUG, BIOLOGICAL, DEVICE) across all interventions in the study
    return list({iv.get("type", "OTHER") for iv in extract_interventions(s) if iv.get("type")})
