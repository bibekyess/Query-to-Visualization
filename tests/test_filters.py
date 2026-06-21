"""Tests for the Essie filter.advanced builder."""
from __future__ import annotations

from app.clinicaltrials.filters import build_essie


def test_none_when_no_criteria():
    assert build_essie(None, None, None, None) is None


def test_single_phase_canonical_passthrough():
    assert build_essie(["PHASE3"], None, None, None) == "AREA[Phase]PHASE3"


def test_phase_shorthand_normalized():
    assert build_essie(["3"], None, None, None) == "AREA[Phase]PHASE3"
    assert build_essie(["phase 1"], None, None, None) == "AREA[Phase]PHASE1"


def test_multiple_phases_wrapped_in_or():
    assert build_essie(["PHASE1", "PHASE2"], None, None, None) == (
        "(AREA[Phase]PHASE1 OR AREA[Phase]PHASE2)"
    )


def test_year_range_open_ended_sentinels():
    assert build_essie(None, 2015, None, None) == "AREA[StartDate]RANGE[2015-01-01,MAX]"
    assert build_essie(None, None, 2020, None) == "AREA[StartDate]RANGE[MIN,2020-12-31]"
    assert build_essie(None, 2015, 2020, None) == "AREA[StartDate]RANGE[2015-01-01,2020-12-31]"


def test_country_clause():
    assert build_essie(None, None, None, "France") == "AREA[LocationCountry]France"


def test_criteria_combined_with_and():
    out = build_essie(["PHASE3"], 2015, None, "Japan")
    assert out == (
        "AREA[Phase]PHASE3 AND AREA[StartDate]RANGE[2015-01-01,MAX] "
        "AND AREA[LocationCountry]Japan"
    )
