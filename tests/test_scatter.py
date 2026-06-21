"""Tests for the scatter path: duration extraction, scatter_points, and finalize."""
from __future__ import annotations

from app.clinicaltrials.extractors import extract_duration_days, extract_start_year
from app.tools import store
from app.tools.finalize import finalize_visualization
from app.tools.scatter import scatter_points
from tests.conftest import make_study


def _load(studies: list[dict], *, total: int | None = None) -> str:
    fetched = len(studies)
    store.DATASETS["d"] = studies
    store.DATASET_META["d"] = {
        "total_count": total if total is not None else fetched,
        "fetched_count": fetched,
        "query_params": {"query.cond": "cancer"},
    }
    return "d"


def test_duration_days_full_dates():
    s = make_study(start_date="2020-01-01", completion_date="2020-12-31")
    assert extract_duration_days(s) == 365


def test_duration_days_partial_dates():
    # "2020" -> 2020-01-01, "2021-06" -> 2021-06-01; 366 (leap 2020) + 151 days = 517
    s = make_study(start_date="2020", completion_date="2021-06")
    assert extract_duration_days(s) == 517


def test_duration_days_missing_or_negative():
    assert extract_duration_days(make_study(start_date="2020-01-01")) is None       # no completion
    assert extract_duration_days(make_study(completion_date="2020-01-01")) is None  # no start
    # completion before start -> None
    assert extract_duration_days(make_study(start_date="2021-01-01", completion_date="2020-01-01")) is None


def test_start_year():
    assert extract_start_year(make_study(start_date="2019-05-01")) == 2019
    assert extract_start_year(make_study(start_date=None)) is None


def test_scatter_builds_points_and_skips_missing():
    dsid = _load([
        make_study(nct_id="A", enrollment=100, start_date="2020-01-01", completion_date="2020-12-31"),
        make_study(nct_id="B", enrollment=None, start_date="2020-01-01", completion_date="2020-12-31"),  # no x
        make_study(nct_id="C", enrollment=50, start_date="2020-01-01"),  # no duration -> no y
    ])
    out = scatter_points(dsid, x_field="enrollment", y_field="duration_days")
    assert set(out) == {"result_id", "num_points", "x_field", "y_field"}
    assert out["num_points"] == 1   # only study A has both values
    points = store.SCATTER_RESULTS[out["result_id"]]["points"]
    assert points[0]["x"] == 100 and points[0]["y"] == 365
    assert points[0]["nct_id"] == "A"
    assert points[0]["citations"][0]["nct_id"] == "A"


def test_scatter_caps_points():
    studies = [
        make_study(nct_id=f"N{i}", enrollment=i + 1, start_date="2020", completion_date="2021")
        for i in range(10)
    ]
    dsid = _load(studies)
    out = scatter_points(dsid, x_field="enrollment", y_field="start_year", max_points=3)
    assert out["num_points"] == 3
    assert store.SCATTER_RESULTS[out["result_id"]]["truncated"] is True


def test_scatter_finalizes_to_scatter_type():
    dsid = _load([make_study(nct_id="A", enrollment=100, start_date="2020-01-01", completion_date="2020-12-31")])
    out = scatter_points(dsid, x_field="enrollment", y_field="duration_days")
    resp = finalize_visualization(out["result_id"], "Enrollment vs duration", encoding={})
    assert resp.visualization.type == "scatter"
    assert resp.visualization.encoding == {"x": {"field": "enrollment"}, "y": {"field": "duration_days"}}
    assert resp.visualization.data[0]["nct_id"] == "A"
    assert resp.response_metadata.counts_exact is False


def test_scatter_unsupported_field():
    dsid = _load([make_study(enrollment=10)])
    assert "error" in scatter_points(dsid, x_field="enrollment", y_field="phase")


def test_scatter_missing_dataset():
    assert "error" in scatter_points("nope", x_field="enrollment", y_field="duration_days")
