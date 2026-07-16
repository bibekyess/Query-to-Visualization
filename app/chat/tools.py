"""
Chat-agent tools: PubMed search, clinical-trial lookup, and visualization.

Each tool returns (model_text, sources, extra_events):
  - model_text:  what the LLM reads next turn (compact, citation-numbered),
  - sources:     Source records for the frontend citation panel,
  - extra_events: SSE events to forward directly (e.g. a rendered visualization).

The SourceRegistry assigns stable [n] indices across all tool calls in one chat
turn so the model can cite "[1][3]" and the frontend can resolve them.
"""
from __future__ import annotations

from typing import Any

import structlog

from app.agent import run_agent
from app.clinicaltrials import client as ct_client
from app.models import Filters, QueryRequest
from app.pubmed import search_articles

log = structlog.get_logger(__name__)

CHAT_TOOLS = [
    {
        "name": "search_pubmed",
        "description": (
            "Search PubMed for peer-reviewed medical literature. Use for medical "
            "knowledge questions (mechanisms, treatments, evidence, safety, guidelines). "
            "Returns numbered sources [n] with titles and abstracts — cite these numbers "
            "inline in your answer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "PubMed search query, e.g. 'pembrolizumab NSCLC first-line efficacy'",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of articles to fetch (default 5, max 10)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_clinical_trials",
        "description": (
            "Look up individual clinical trials on ClinicalTrials.gov. Use when the user "
            "asks about specific trials, recruiting studies, or trial details. Returns "
            "numbered sources [n] with NCT IDs, status, and phase — cite these numbers "
            "inline. For counts/trends/comparisons use create_visualization instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "condition": {"type": "string", "description": "Disease or condition"},
                "intervention": {"type": "string", "description": "Drug or intervention name"},
                "query_term": {"type": "string", "description": "Free-text fallback search"},
                "status": {"type": "string", "description": "e.g. RECRUITING, COMPLETED"},
                "max_results": {"type": "integer", "description": "Default 5, max 10"},
            },
            "required": [],
        },
    },
    {
        "name": "create_visualization",
        "description": (
            "Generate an interactive chart from live ClinicalTrials.gov data. Use when "
            "the answer benefits from aggregate data: counts over time, comparisons "
            "between drugs/conditions, phase or sponsor breakdowns, geographic spread, "
            "enrollment distributions, or co-occurrence networks. Pass a self-contained "
            "natural-language description of the chart. The chart renders in the UI "
            "automatically — after calling, briefly explain what it shows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Self-contained chart request, e.g. 'Number of pembrolizumab "
                        "trials per year since 2015' or 'Compare phase distribution of "
                        "semaglutide vs tirzepatide trials'"
                    ),
                },
                "condition": {"type": "string", "description": "Optional condition filter"},
                "drug_name": {"type": "string", "description": "Optional drug filter"},
                "start_year": {"type": "integer", "description": "Optional start-year filter"},
                "end_year": {"type": "integer", "description": "Optional end-year filter"},
            },
            "required": ["query"],
        },
    },
]

_TOOL_LABELS = {
    "search_pubmed": "Searching PubMed",
    "search_clinical_trials": "Searching ClinicalTrials.gov",
    "create_visualization": "Building visualization",
}


def tool_label(name: str) -> str:
    return _TOOL_LABELS.get(name, name)


class SourceRegistry:
    """Assigns stable citation numbers [1..n] to sources across one chat request."""

    def __init__(self) -> None:
        self._by_key: dict[str, dict] = {}
        self._ordered: list[dict] = []

    def add(self, key: str, source: dict) -> dict:
        if key in self._by_key:
            return self._by_key[key]
        source = {**source, "index": len(self._ordered) + 1}
        self._by_key[key] = source
        self._ordered.append(source)
        return source

    @property
    def sources(self) -> list[dict]:
        return list(self._ordered)


def _run_search_pubmed(args: dict, registry: SourceRegistry):
    articles = search_articles(args.get("query", ""), int(args.get("max_results") or 5))
    if not articles:
        return "No PubMed articles found for this query. Try different terms.", [], []

    lines, new_sources = [], []
    for a in articles:
        src = registry.add(f"pubmed:{a.pmid}", {
            "type": "pubmed",
            "id": a.pmid,
            "title": a.title,
            "url": a.url,
            "journal": a.journal,
            "year": a.year,
            "authors": a.authors[:3],
        })
        new_sources.append(src)
        abstract = a.abstract[:1200] + ("…" if len(a.abstract) > 1200 else "")
        who = ", ".join(a.authors[:3]) + (" et al." if len(a.authors) > 3 else "")
        lines.append(
            f"[{src['index']}] {a.title} — {who} ({a.journal}, {a.year}). "
            f"PMID {a.pmid}.\nAbstract: {abstract or '(no abstract available)'}"
        )
    return "\n\n".join(lines), new_sources, []


# Minimal projection for trial lookups — full records are unnecessary for citations.
_TRIAL_FIELDS = "NCTId,BriefTitle,Phase,OverallStatus,StartDate,LeadSponsorName,Condition,InterventionName,BriefSummary"


def _run_search_trials(args: dict, registry: SourceRegistry):
    params: dict[str, str] = {}
    if args.get("condition"):
        params["query.cond"] = args["condition"]
    if args.get("intervention"):
        params["query.intr"] = args["intervention"]
    if args.get("query_term") and not (args.get("condition") or args.get("intervention")):
        params["query.term"] = args["query_term"]
    if args.get("status"):
        params["filter.overallStatus"] = str(args["status"]).upper()
    if not params:
        return "Provide at least one of condition, intervention, or query_term.", [], []

    n = max(1, min(int(args.get("max_results") or 5), 10))
    data = ct_client._get_with_retry(
        ct_client._studies_url(),
        {**params, "fields": _TRIAL_FIELDS, "pageSize": str(n)},
    )
    studies = data.get("studies", [])
    if not studies:
        return "No trials matched. Try broader terms.", [], []

    lines, new_sources = [], []
    for s in studies:
        proto = s.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        status_mod = proto.get("statusModule", {})
        design = proto.get("designModule", {})
        nct_id = ident.get("nctId", "")
        title = ident.get("briefTitle", "")
        status = status_mod.get("overallStatus", "")
        phases = "/".join(design.get("phases", []) or [])
        sponsor = (
            proto.get("sponsorCollaboratorsModule", {})
            .get("leadSponsor", {}).get("name", "")
        )
        summary = (
            proto.get("descriptionModule", {}).get("briefSummary", "")
            if proto.get("descriptionModule") else ""
        )[:600]

        src = registry.add(f"trial:{nct_id}", {
            "type": "trial",
            "id": nct_id,
            "title": title,
            "url": f"https://clinicaltrials.gov/study/{nct_id}",
            "status": status,
            "phase": phases,
            "sponsor": sponsor,
        })
        new_sources.append(src)
        lines.append(
            f"[{src['index']}] {nct_id}: {title} — {status}"
            f"{', ' + phases if phases else ''}{', sponsor: ' + sponsor if sponsor else ''}."
            f"\n{summary}"
        )
    return "\n\n".join(lines), new_sources, []


def _run_create_visualization(args: dict, registry: SourceRegistry):
    filters = Filters(
        condition=args.get("condition"),
        drug_name=args.get("drug_name"),
        start_year=args.get("start_year"),
        end_year=args.get("end_year"),
    )
    has_filters = bool(filters.model_dump(exclude_none=True))
    request = QueryRequest(query=args["query"], filters=filters if has_filters else None)
    try:
        response = run_agent(request)
    except Exception as exc:
        log.warning("chat.viz_failed", error=str(exc))
        return f"Visualization failed: {exc}. Answer from other sources instead.", [], []

    payload = response.model_dump(mode="json")
    viz = response.visualization
    if viz is None:
        return f"No chart produced: {response.message}", [], []

    meta = response.response_metadata
    # Compact summary for the model — the full payload goes only to the frontend.
    top = ""
    if viz.data:
        keys = [k for k in viz.data[0] if k not in ("citations", "count")][:1]
        if keys:
            rows = sorted(viz.data, key=lambda d: d.get("count", 0), reverse=True)[:5]
            top = "; top values: " + ", ".join(
                f"{r.get(keys[0])}={r.get('count')}" for r in rows if r.get(keys[0]) is not None
            )
    summary = (
        f"Rendered a {viz.type} titled {viz.title!r} in the UI "
        f"({meta.total_count:,} matching trials, {meta.fetched_count:,} analyzed{top}). "
        f"{meta.query_interpretation} Briefly explain what the chart shows; do not "
        f"re-list its raw data."
    )
    return summary, [], [{"type": "visualization", "payload": payload}]


TOOL_RUNNERS = {
    "search_pubmed": _run_search_pubmed,
    "search_clinical_trials": _run_search_trials,
    "create_visualization": _run_create_visualization,
}


def run_tool(name: str, args: dict, registry: SourceRegistry):
    """Execute a chat tool. Errors become text results so the model can recover."""
    runner = TOOL_RUNNERS.get(name)
    if runner is None:
        return f"Unknown tool: {name}", [], []
    try:
        return runner(args, registry)
    except Exception as exc:  # network failures, bad args — feed back, don't 500
        log.warning("chat.tool_error", tool=name, error=str(exc), exc_info=True)
        return f"Tool error ({type(exc).__name__}): {exc}", [], []
