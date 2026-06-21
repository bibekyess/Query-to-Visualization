"""ClinicalTrials.gov v2 HTTP client — verified against the live API."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from app.config import get_settings

# PascalCase token names are verified to work for field projection (cuts response size ~10×).
# The API also accepts dotted JSON paths, but PascalCase is shorter for the query string.
STANDARD_FIELDS = (
    "NCTId,BriefTitle,Phase,OverallStatus,StartDate,CompletionDate,"
    "LeadSponsorName,LeadSponsorClass,Condition,InterventionName,"
    "InterventionType,LocationCountry,EnrollmentCount,BriefSummary,StudyType"
)


def _studies_url() -> str:
    return f"{get_settings().ct_base_url}/studies"


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
    data = _get_with_retry(_studies_url(), p)
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
        data = _get_with_retry(_studies_url(), p)
        batch = data.get("studies", [])
        studies.extend(batch)
        page_token = data.get("nextPageToken")       # RESPONSE key — different name on purpose
        if not page_token or not batch:
            break

    return studies[:max_records]
