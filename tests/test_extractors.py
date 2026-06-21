"""Tests for field extraction from study records, incl. missing/multi-valued fields."""
from __future__ import annotations

from app.clinicaltrials import extractors as ct
from tests.conftest import make_study


def test_basic_scalar_fields():
    s = make_study(nct_id="NCT01", title="T", status="COMPLETED",
                   sponsor_name="Pfizer", sponsor_class="INDUSTRY", study_type="OBSERVATIONAL")
    assert ct.extract_nct_id(s) == "NCT01"
    assert ct.extract_brief_title(s) == "T"
    assert ct.extract_status(s) == "COMPLETED"
    assert ct.extract_sponsor_name(s) == "Pfizer"
    assert ct.extract_sponsor_class(s) == "INDUSTRY"
    assert ct.extract_study_type(s) == "OBSERVATIONAL"


def test_missing_fields_return_defaults():
    empty = {}  # no protocolSection at all
    assert ct.extract_nct_id(empty) == ""
    assert ct.extract_status(empty) == "UNKNOWN"
    assert ct.extract_sponsor_name(empty) == "Unknown"
    assert ct.extract_sponsor_class(empty) == "OTHER"
    assert ct.extract_phases(empty) == []
    assert ct.extract_conditions(empty) == []
    assert ct.extract_start_date(empty) is None
    assert ct.extract_enrollment(empty) is None


def test_multivalued_phases_and_conditions():
    s = make_study(phases=["PHASE1", "PHASE2"], conditions=["Cancer", "Melanoma"])
    assert ct.extract_phases(s) == ["PHASE1", "PHASE2"]
    assert ct.extract_conditions(s) == ["Cancer", "Melanoma"]


def test_countries_deduped_preserving_order():
    s = make_study(countries=["US", "France", "US", "Japan", "France"])
    assert ct.extract_countries(s) == ["US", "France", "Japan"]


def test_intervention_types_deduped():
    s = make_study(interventions=[
        {"type": "DRUG", "name": "A"},
        {"type": "DRUG", "name": "B"},
        {"type": "DEVICE", "name": "C"},
    ])
    assert sorted(ct.extract_intervention_types(s)) == ["DEVICE", "DRUG"]
    assert [iv["name"] for iv in ct.extract_interventions(s)] == ["A", "B", "C"]


def test_enrollment_coerces_and_handles_garbage():
    assert ct.extract_enrollment(make_study(enrollment=120)) == 120
    assert ct.extract_enrollment(make_study(enrollment="350")) == 350
    # non-numeric enrollment string -> None, not a crash
    bad = make_study()
    bad["protocolSection"]["designModule"]["enrollmentInfo"] = {"count": "many"}
    assert ct.extract_enrollment(bad) is None


def test_date_formats_preserved_verbatim():
    # The API returns YYYY, YYYY-MM, or YYYY-MM-DD; extractor must not reformat.
    assert ct.extract_start_date(make_study(start_date="2015")) == "2015"
    assert ct.extract_start_date(make_study(start_date="2015-06")) == "2015-06"
    assert ct.extract_completion_date(make_study(completion_date="2020-12-31")) == "2020-12-31"
