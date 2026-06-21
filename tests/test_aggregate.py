"""Tests for aggregation, the count tiers, and the labels-only LLM contract."""
from __future__ import annotations

import pytest

from app.tools import store
from app.tools.aggregate import aggregate
from tests.conftest import make_study


def _load(studies: list[dict], *, total: int | None = None, query_params: dict | None = None) -> str:
    fetched = len(studies)
    store.DATASETS["d"] = studies
    store.DATASET_META["d"] = {
        "total_count": total if total is not None else fetched,
        "fetched_count": fetched,
        "query_params": query_params or {},
    }
    return "d"


def test_dataset_not_found():
    assert "error" in aggregate("missing", group_by="phase")


def test_returns_labels_only_no_counts():
    # The LLM must never receive numeric values — only labels and a result_id.
    dsid = _load([make_study(phases=["PHASE1"]), make_study(phases=["PHASE2"])])
    out = aggregate(dsid, group_by="phase")
    assert set(out) == {"result_id", "groups", "num_groups"}
    assert all(isinstance(g, str) for g in out["groups"])


def test_full_corpus_counts_are_exact_from_sample():
    # total == fetched -> not truncated -> sample counts are themselves exact.
    dsid = _load([
        make_study(phases=["PHASE1"]),
        make_study(phases=["PHASE2"]),
        make_study(phases=["PHASE2"]),
    ])
    out = aggregate(dsid, group_by="phase")
    res = store.AGG_RESULTS[out["result_id"]]
    assert res["counts_exact"] is True
    counts = {d["phase"]: d["count"] for d in res["data"]}
    assert counts == {"Phase 2": 2, "Phase 1": 1}


def test_multivalued_phase_counted_in_each_bucket():
    dsid = _load([make_study(phases=["PHASE1", "PHASE2"])])
    out = aggregate(dsid, group_by="phase")
    counts = {d["phase"]: d["count"] for d in store.AGG_RESULTS[out["result_id"]]["data"]}
    assert counts == {"Phase 1": 1, "Phase 2": 1}


def test_missing_phase_falls_back_to_na():
    dsid = _load([make_study(phases=None)])
    out = aggregate(dsid, group_by="phase")
    counts = {d["phase"]: d["count"] for d in store.AGG_RESULTS[out["result_id"]]["data"]}
    assert counts == {"N/A": 1}


def test_citations_capped_per_group():
    studies = [make_study(nct_id=f"N{i}", phases=["PHASE1"]) for i in range(10)]
    dsid = _load(studies)
    out = aggregate(dsid, group_by="phase")
    data = store.AGG_RESULTS[out["result_id"]]["data"]
    assert len(data[0]["citations"]) == 3  # citations_per_group default


def test_enrollment_buckets():
    dsid = _load([
        make_study(enrollment=10),
        make_study(enrollment=120),
        make_study(enrollment=120),
        make_study(enrollment=None),
    ])
    out = aggregate(dsid, group_by="enrollment_bucket")
    counts = {d["enrollment_bucket"]: d["count"] for d in store.AGG_RESULTS[out["result_id"]]["data"]}
    assert counts == {"50–199": 2, "< 50": 1, "Unknown": 1}


def test_truncated_enumerable_uses_exact_server_counts(monkeypatch):
    fake = {"AREA[Phase]PHASE1": 10, "AREA[Phase]PHASE3": 30}
    monkeypatch.setattr(
        "app.clinicaltrials.client.count_with_clause",
        lambda base, clause: fake.get(clause, 0),
    )
    # truncated: total (1000) > fetched (2)
    dsid = _load(
        [make_study(nct_id="N1", phases=["PHASE1"]), make_study(nct_id="N2", phases=["PHASE3"])],
        total=1000,
    )
    out = aggregate(dsid, group_by="phase")
    res = store.AGG_RESULTS[out["result_id"]]
    assert res["counts_exact"] is True
    counts = {d["phase"]: d["count"] for d in res["data"]}
    assert counts == {"Phase 3": 30, "Phase 1": 10}  # server totals, not the 1-each sample
    # citations still drawn from the fetched sample
    assert res["data"][0]["citations"][0]["nct_id"] == "N2"


def test_truncated_unbounded_stays_approximate(monkeypatch):
    # Unbounded fields must NOT trigger server count queries; they fall back to the sample.
    def _boom(*a, **k):
        raise AssertionError("count_with_clause should not be called for unbounded fields")

    monkeypatch.setattr("app.clinicaltrials.client.count_with_clause", _boom)
    dsid = _load(
        [make_study(sponsor_name="Acme"), make_study(sponsor_name="Acme"), make_study(sponsor_name="Beta")],
        total=9999,
    )
    out = aggregate(dsid, group_by="sponsor_name")
    res = store.AGG_RESULTS[out["result_id"]]
    assert res["counts_exact"] is False
    counts = {d["sponsor_name"]: d["count"] for d in res["data"]}
    assert counts == {"Acme": 2, "Beta": 1}
