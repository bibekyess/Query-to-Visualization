"""ClinicalTrials.gov v2 API client — verified against live API."""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://clinicaltrials.gov/api/v2"

# PascalCase token names are verified to work for field projection (cuts response size ~10×).
# The API also accepts dotted JSON paths, but PascalCase is shorter for the query string.
STANDARD_FIELDS = (
    "NCTId,BriefTitle,Phase,OverallStatus,StartDate,CompletionDate,"
    "LeadSponsorName,LeadSponsorClass,Condition,InterventionName,"
    "InterventionType,LocationCountry,EnrollmentCount,BriefSummary,StudyType"
)

# The API uses ALL_CAPS enum values; users write things like "3" or "Phase 3".
_PHASE_MAP: dict[str, str] = {
    "1": "PHASE1", "phase1": "PHASE1", "phase 1": "PHASE1",
    "2": "PHASE2", "phase2": "PHASE2", "phase 2": "PHASE2",
    "3": "PHASE3", "phase3": "PHASE3", "phase 3": "PHASE3",
    "4": "PHASE4", "phase4": "PHASE4", "phase 4": "PHASE4",
    "early1": "EARLY_PHASE1", "early phase 1": "EARLY_PHASE1",
}


def build_essie(
    phases: list[str] | None,
    start_year: int | None,
    end_year: int | None,
    country: str | None,
) -> str | None:
    """
    Build a filter.advanced Essie expression from structured filters.

    Essie is the ClinicalTrials.gov query language for the filter.advanced parameter.
    Dedicated filter.phase / filter.country params do NOT exist — Essie is the only way.
    Multiple criteria are combined with AND; multiple phases use OR inside parentheses.
    """
    parts: list[str] = []

    if phases:
        phase_exprs = [
            f"AREA[Phase]{_PHASE_MAP.get(p.lower().strip(), 'PHASE' + p.strip())}"
            for p in phases
        ]
        # Single phase: plain expression.  Multiple: wrap in parentheses for correct OR grouping.
        parts.append(
            phase_exprs[0] if len(phase_exprs) == 1
            else "(" + " OR ".join(phase_exprs) + ")"
        )

    if start_year or end_year:
        # RANGE uses MIN/MAX as open-ended sentinels when one bound is absent.
        start = f"{start_year}-01-01" if start_year else "MIN"
        end = f"{end_year}-12-31" if end_year else "MAX"
        parts.append(f"AREA[StartDate]RANGE[{start},{end}]")

    if country:
        parts.append(f"AREA[LocationCountry]{country}")

    return " AND ".join(parts) if parts else None


def _get_with_retry(url: str, params: dict) -> dict:
    """
    Fetch a JSON response using urllib (Python's built-in HTTP client).

    urllib uses the OS TLS stack (Windows Schannel on Windows), which passes
    ClinicalTrials.gov's TLS fingerprint check. httpx uses its own TLS stack
    and gets 403 even with a spoofed User-Agent.

    Retries with exponential back-off on HTTP 429 (rate limit: ~50 req/min).
    """
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("Max retries exceeded after 429 responses")


def count_studies(params: dict) -> int:
    """
    Get the authoritative server-side count for a query without fetching any records.

    We call this before paginating so we know upfront whether the query returns results,
    and so we can later compare our client-side count against the server total as a
    hallucination-prevention check (count_verified in ResponseMetadata).
    """
    p = {**params, "countTotal": "true", "pageSize": "1"}
    data = _get_with_retry(f"{BASE_URL}/studies", p)
    return data.get("totalCount", 0)


def fetch_all_studies(params: dict, max_records: int = 5000) -> list[dict]:
    """
    Paginate through all matching studies with standard field projection.

    Key asymmetry in the API (easy to get wrong):
      - The RESPONSE includes "nextPageToken"
      - The next REQUEST must send it back as "pageToken"
    Both keys exist; mixing them up silently returns the first page again.

    pageSize=1000 is the maximum the API allows; anything larger is clamped to 1000.
    """
    p = {**params, "fields": STANDARD_FIELDS, "pageSize": "1000"}
    studies: list[dict] = []
    page_token: str | None = None

    while len(studies) < max_records:
        if page_token:
            p = {**p, "pageToken": page_token}      # REQUEST key
        data = _get_with_retry(f"{BASE_URL}/studies", p)
        batch = data.get("studies", [])
        studies.extend(batch)
        page_token = data.get("nextPageToken")       # RESPONSE key — different name on purpose
        if not page_token or not batch:
            break

    return studies[:max_records]


# --- Field extractors ---
# All study fields live inside a deeply nested "protocolSection" object.
# _get() is a safe path-traversal helper so we never get KeyError on missing fields.

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
