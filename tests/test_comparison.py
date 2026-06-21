"""Tests for multi-dataset comparison (aggregate_comparison) and grouped_bar finalize."""
from __future__ import annotations

from app.tools import store
from app.tools.aggregate import aggregate_comparison
from app.tools.finalize import finalize_visualization
from app.viz import select
from tests.conftest import make_study


def _load(key: str, studies: list[dict], *, total: int | None = None) -> None:
    fetched = len(studies)
    store.DATASETS[key] = studies
    store.DATASET_META[key] = {
        "total_count": total if total is not None else fetched,
        "fetched_count": fetched,
        "query_params": {"query.intr": key},
    }


def test_selector_grouped_categorical_is_grouped_bar():
    assert select("phase", None, grouped=True) == "grouped_bar"
    assert select("phase", None, grouped=False) == "bar_chart"


def test_selector_grouped_time_is_multiseries_time():
    assert select("start_year", None, grouped=True) == "time_series"


def test_comparison_emits_long_rows_with_series_and_counts():
    _load("a", [
        make_study(nct_id="A1", phases=["PHASE1"]),
        make_study(nct_id="A2", phases=["PHASE1"]),
        make_study(nct_id="A3", phases=["PHASE2"]),
    ])
    _load("b", [
        make_study(nct_id="B1", phases=["PHASE2"]),
        make_study(nct_id="B2", phases=["PHASE2"]),
        make_study(nct_id="B3", phases=["PHASE2"]),
    ])
    out = aggregate_comparison(
        [{"dataset_id": "a", "label": "Drug A"}, {"dataset_id": "b", "label": "Drug B"}],
        group_by="phase",
    )
    # LLM only ever sees labels — never counts.
    assert set(out) == {"result_id", "groups", "series", "num_groups"}
    assert out["series"] == ["Drug A", "Drug B"]
    assert out["groups"] == ["Phase 2", "Phase 1"]   # ranked by summed count (4 vs 2)

    data = store.AGG_RESULTS[out["result_id"]]["data"]
    counts = {(d["phase"], d["series"]): d["count"] for d in data}
    assert counts[("Phase 2", "Drug A")] == 1
    assert counts[("Phase 2", "Drug B")] == 3
    assert counts[("Phase 1", "Drug A")] == 2
    assert counts[("Phase 1", "Drug B")] == 0   # missing combo aligned to 0


def test_comparison_finalizes_to_grouped_bar():
    _load("a", [make_study(nct_id="A1", phases=["PHASE1"])])
    _load("b", [make_study(nct_id="B1", phases=["PHASE2"])])
    out = aggregate_comparison(
        [{"dataset_id": "a", "label": "A"}, {"dataset_id": "b", "label": "B"}],
        group_by="phase",
    )
    resp = finalize_visualization(out["result_id"], "A vs B by phase", encoding={})
    assert resp.visualization.type == "grouped_bar"
    assert resp.visualization.encoding["series"] == {"field": "series"}
    assert resp.visualization.encoding["x"] == {"field": "phase"}
    # combined corpus totals across both series
    assert resp.response_metadata.fetched_count == 2
    # every datum carries citations with real nct_ids
    assert resp.visualization.data[0]["citations"][0]["nct_id"] in {"A1", "B1"}


def test_comparison_time_field_finalizes_to_time_series():
    _load("a", [make_study(nct_id="A1", start_date="2020-01-01")])
    _load("b", [make_study(nct_id="B1", start_date="2021-01-01")])
    out = aggregate_comparison(
        [{"dataset_id": "a", "label": "A"}, {"dataset_id": "b", "label": "B"}],
        group_by="start_year",
    )
    resp = finalize_visualization(out["result_id"], "A vs B over time", encoding={})
    assert resp.visualization.type == "time_series"
    assert resp.response_metadata.time_granularity == "year"


def test_comparison_requires_two_series():
    _load("a", [make_study(phases=["PHASE1"])])
    assert "error" in aggregate_comparison([{"dataset_id": "a", "label": "A"}], group_by="phase")


def test_comparison_missing_dataset_errors():
    _load("a", [make_study(phases=["PHASE1"])])
    out = aggregate_comparison(
        [{"dataset_id": "a", "label": "A"}, {"dataset_id": "nope", "label": "B"}],
        group_by="phase",
    )
    assert "error" in out
