"""
Standalone MCP server exposing the medical research + visualization tools.

Run for any MCP client (Claude Desktop, etc.):

    uv run python mcp_server.py            # stdio transport (default)
    MCP_TRANSPORT=http uv run python mcp_server.py   # streamable HTTP on :8001

The chatbot backend consumes the same underlying tool layer (app.chat.tools /
app.agent), so tool logic lives in one place — this server is a thin MCP wrapper.

The create_visualization tool returns a Vega-Lite-shaped artifact plus a
compact text summary, so an MCP client that renders artifacts can display the
chart while the model reads the summary.
"""
from __future__ import annotations

import json
import os

from fastmcp import FastMCP

from app.agent import run_agent
from app.chat.tools import SourceRegistry, _run_search_pubmed, _run_search_trials
from app.models import Filters, QueryRequest

mcp = FastMCP(
    name="clinicaltrials-viz",
    instructions=(
        "Medical research tools backed by live PubMed and ClinicalTrials.gov data. "
        "Use search_pubmed for literature, search_clinical_trials for specific studies, "
        "and create_visualization for charts of aggregate trial data (counts, trends, "
        "comparisons, distributions, networks)."
    ),
)


@mcp.tool
def search_pubmed(query: str, max_results: int = 5) -> str:
    """Search PubMed for peer-reviewed medical literature.

    Returns numbered sources with titles and abstracts. Use for medical-knowledge
    questions (mechanisms, efficacy, safety, guidelines).

    Args:
        query: PubMed search query, e.g. 'pembrolizumab NSCLC first-line efficacy'.
        max_results: Number of articles to fetch (1-10, default 5).
    """
    text, _sources, _extra = _run_search_pubmed(
        {"query": query, "max_results": max_results}, SourceRegistry()
    )
    return text


@mcp.tool
def search_clinical_trials(
    condition: str = "",
    intervention: str = "",
    query_term: str = "",
    status: str = "",
    max_results: int = 5,
) -> str:
    """Look up individual clinical trials on ClinicalTrials.gov.

    Returns numbered sources with NCT IDs, status, and phase. Use for specific
    trials or recruiting studies; for counts/trends use create_visualization.

    Args:
        condition: Disease or condition.
        intervention: Drug or intervention name.
        query_term: Free-text fallback search.
        status: e.g. RECRUITING, COMPLETED.
        max_results: Number of trials (1-10, default 5).
    """
    args = {
        "condition": condition or None,
        "intervention": intervention or None,
        "query_term": query_term or None,
        "status": status or None,
        "max_results": max_results,
    }
    text, _sources, _extra = _run_search_trials(
        {k: v for k, v in args.items() if v is not None}, SourceRegistry()
    )
    return text


@mcp.tool
def create_visualization(
    query: str,
    condition: str = "",
    drug_name: str = "",
    start_year: int = 0,
    end_year: int = 0,
) -> dict:
    """Generate an interactive chart specification from live ClinicalTrials.gov data.

    Use for aggregate data: counts over time, comparisons, phase/sponsor/geographic
    breakdowns, enrollment distributions, or co-occurrence networks.

    Returns a dict with a text `summary` and the full `visualization` spec
    (Vega-Lite-shaped `data`/`encoding`, or `nodes`/`edges` for networks) plus
    `response_metadata` — ready for an artifact renderer.

    Args:
        query: Self-contained chart request, e.g. 'pembrolizumab trials per year since 2015'.
        condition: Optional condition filter.
        drug_name: Optional drug filter.
        start_year: Optional start-year filter (0 = unset).
        end_year: Optional end-year filter (0 = unset).
    """
    filters = Filters(
        condition=condition or None,
        drug_name=drug_name or None,
        start_year=start_year or None,
        end_year=end_year or None,
    )
    has_filters = bool(filters.model_dump(exclude_none=True))
    request = QueryRequest(query=query, filters=filters if has_filters else None)
    response = run_agent(request)
    payload = response.model_dump(mode="json")

    viz = response.visualization
    if viz is None:
        summary = f"No chart produced: {response.message}"
    else:
        meta = response.response_metadata
        summary = (
            f"{viz.type} titled {viz.title!r} — {meta.total_count:,} matching trials, "
            f"{meta.fetched_count:,} analyzed. {meta.query_interpretation}"
        )
    return {"summary": summary, **payload}


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.run(transport="http", host="0.0.0.0", port=int(os.environ.get("MCP_PORT", "8001")))
    else:
        mcp.run()
