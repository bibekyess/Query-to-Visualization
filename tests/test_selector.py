"""Tests for deterministic viz-type selection."""
from __future__ import annotations

from app.viz.selector import select


def test_network_hint_always_wins():
    assert select("condition", "network_graph") == "network_graph"


def test_time_fields_force_time_series():
    for f in ("start_year", "start_month", "completion_year"):
        assert select(f, None) == "time_series"
    # even a conflicting hint can't override an inherently ordered x-axis
    assert select("start_year", "bar_chart") == "time_series"


def test_enrollment_bucket_forces_histogram():
    assert select("enrollment_bucket", None) == "histogram"


def test_default_is_bar_chart():
    assert select("phase", None) == "bar_chart"
    assert select("country", None) == "bar_chart"


def test_unrecognised_hint_ignored():
    assert select("phase", "pie_chart") == "bar_chart"
