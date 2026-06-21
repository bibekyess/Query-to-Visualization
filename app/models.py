from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


# --- Request models ---

class Filters(BaseModel):
    # All fields are optional; the agent uses whichever are provided to narrow the API query.
    drug_name: str | None = None
    condition: str | None = None
    phase: list[str] | None = None   # list because a query can cover multiple phases, e.g. ["1", "2"]
    sponsor: str | None = None
    country: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    status: str | None = None        # e.g. "RECRUITING", "COMPLETED"


class QueryRequest(BaseModel):
    query: str                       # natural-language question — the only required field
    filters: Filters | None = None


# --- Citation (deep citations bonus) ---

class Citation(BaseModel):
    # Each datum in the response carries back-links to the real trial records that produced it.
    nct_id: str     # e.g. "NCT04345250" — links to clinicaltrials.gov/study/<nct_id>
    excerpt: str    # first 200 chars of briefSummary, proving which record contributed


# --- Network graph models ---

class NetworkNode(BaseModel):
    id: str
    label: str
    weight: int    # how many studies mention this entity (used to size nodes in a renderer)


class NetworkEdge(BaseModel):
    source: str
    target: str
    weight: int    # how many studies list both endpoints together (co-occurrence strength)


# --- Output models ---

class Visualization(BaseModel):
    type: str                              # bar_chart | time_series | histogram | scatter | network_graph | grouped_bar
    title: str
    encoding: dict[str, Any]              # Vega-Lite-style channel map, e.g. {"x": {"field": "phase"}, "y": {"field": "count"}}
    data: list[dict[str, Any]] | None = None    # None for network_graph — use nodes/edges instead
    nodes: list[NetworkNode] | None = None      # only populated for network_graph
    edges: list[NetworkEdge] | None = None      # only populated for network_graph
    filters: dict[str, Any] = Field(default_factory=dict)  # mirrors the query params applied, for transparency


class ResponseMetadata(BaseModel):
    total_count: int          # authoritative server-side count from ClinicalTrials.gov countTotal
    fetched_count: int        # how many records were actually downloaded and aggregated
    time_granularity: str | None = None   # "month" or "year" when the x-axis is a date field
    truncated: bool = False               # True when total_count > fetched_count (sample only)
    count_verified: bool = False          # True when fetched_count == total_count (no sampling)
    count_server: int | None = None       # populated when counts don't match, to surface the gap
    query_interpretation: str = ""
    warnings: list[str] = Field(default_factory=list)


class VisualizationResponse(BaseModel):
    visualization: Visualization
    response_metadata: ResponseMetadata
