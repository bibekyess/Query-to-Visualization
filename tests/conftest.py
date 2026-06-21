"""Shared fixtures: a study-dict factory and a clean in-memory store per test."""
from __future__ import annotations

import pytest

from app.tools import store


def make_study(
    *,
    nct_id: str = "NCT00000000",
    title: str = "A study",
    phases: list[str] | None = None,
    status: str = "RECRUITING",
    start_date: str | None = None,
    completion_date: str | None = None,
    sponsor_name: str = "Acme",
    sponsor_class: str = "INDUSTRY",
    conditions: list[str] | None = None,
    interventions: list[dict] | None = None,
    countries: list[str] | None = None,
    enrollment: int | None = None,
    study_type: str = "INTERVENTIONAL",
    brief_summary: str = "Summary text.",
) -> dict:
    """Build a study dict shaped like a real ClinicalTrials.gov v2 record.

    Only the fields the extractors read are populated; omitted pieces stay absent
    so tests can exercise the missing-field paths.
    """
    protocol: dict = {
        "identificationModule": {"nctId": nct_id, "briefTitle": title},
        "statusModule": {"overallStatus": status},
        "designModule": {"studyType": study_type},
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": sponsor_name, "class": sponsor_class}
        },
        "descriptionModule": {"briefSummary": brief_summary},
    }
    if phases is not None:
        protocol["designModule"]["phases"] = phases
    if start_date is not None:
        protocol["statusModule"]["startDateStruct"] = {"date": start_date}
    if completion_date is not None:
        protocol["statusModule"]["completionDateStruct"] = {"date": completion_date}
    if conditions is not None:
        protocol["conditionsModule"] = {"conditions": conditions}
    if interventions is not None:
        protocol["armsInterventionsModule"] = {"interventions": interventions}
    if countries is not None:
        protocol["contactsLocationsModule"] = {
            "locations": [{"country": c} for c in countries]
        }
    if enrollment is not None:
        protocol["designModule"]["enrollmentInfo"] = {"count": enrollment}
    return {"protocolSection": protocol}


@pytest.fixture
def study_factory():
    return make_study


@pytest.fixture(autouse=True)
def clean_store():
    """Reset the module-level in-memory store before and after every test."""
    for d in (store.DATASETS, store.DATASET_META, store.AGG_RESULTS,
              store.NET_RESULTS, store.SCATTER_RESULTS):
        d.clear()
    yield
    for d in (store.DATASETS, store.DATASET_META, store.AGG_RESULTS,
              store.NET_RESULTS, store.SCATTER_RESULTS):
        d.clear()
