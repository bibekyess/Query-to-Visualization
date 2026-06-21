from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


# --- Enums ---

class Phase(str, Enum):
    """Canonical ClinicalTrials.gov Phase values (verified against the live API)."""
    EARLY_PHASE1 = "EARLY_PHASE1"
    PHASE1 = "PHASE1"
    PHASE2 = "PHASE2"
    PHASE3 = "PHASE3"
    PHASE4 = "PHASE4"
    NA = "NA"


# --- Request models ---

class Filters(BaseModel):
    # use_enum_values so phase serializes back to plain strings (e.g. for the agent prompt).
    model_config = ConfigDict(use_enum_values=True)

    # All fields are optional; the agent uses whichever are provided to narrow the API query.
    drug_name: str | None = None
    condition: str | None = None
    phase: list[Phase] | None = None   # canonical Phase values; multiple = OR, e.g. ["PHASE1", "PHASE2"]
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
    nct_id: str        # e.g. "NCT04345250" — links to clinicaltrials.gov/study/<nct_id>
    excerpt: str       # the exact field value(s) placing this record in the bucket
    source_field: str  # JSON path the excerpt was read from, e.g. "...designModule.phases"


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
    type: str                              # bar_chart | time_series | histogram | network_graph
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
    counts_exact: bool = False            # True when per-bucket counts are server-authoritative
                                          # (full corpus fetched, or computed via per-group countTotal),
                                          # False when bars are approximated from a truncated sample
    count_server: int | None = None       # populated when counts don't match, to surface the gap
    query_interpretation: str = ""
    warnings: list[str] = Field(default_factory=list)


class VisualizationResponse(BaseModel):
    # visualization is None only for the "no data" notice path (see finalize_notice);
    # message carries the human-readable explanation in that case.
    visualization: Visualization | None = None
    message: str | None = None
    response_metadata: ResponseMetadata
