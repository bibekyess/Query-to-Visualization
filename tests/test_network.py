"""Tests for co-occurrence network construction."""
from __future__ import annotations

from app.tools import store
from app.tools.network import build_network
from tests.conftest import make_study


def _load(studies: list[dict]) -> str:
    store.DATASETS["d"] = studies
    store.DATASET_META["d"] = {"total_count": len(studies), "fetched_count": len(studies)}
    return "d"


def test_dataset_not_found():
    assert "error" in build_network("missing", node_type="condition")


def test_node_and_edge_weights():
    dsid = _load([
        make_study(nct_id="N1", conditions=["A", "B"]),
        make_study(nct_id="N2", conditions=["A", "C"]),
    ])
    r = build_network(dsid, node_type="condition")
    nodes = store.NET_RESULTS[r["result_id"]]["nodes"]
    weights = {n["label"]: n["weight"] for n in nodes}
    assert weights == {"A": 2, "B": 1, "C": 1}

    # Edges reference node ids (normalized keys); translate back to labels to assert.
    id_to_label = {n["id"]: n["label"] for n in nodes}
    edges = {
        (id_to_label[e["source"]], id_to_label[e["target"]]): e["weight"]
        for e in store.NET_RESULTS[r["result_id"]]["edges"]
    }
    # A co-occurs with B once and with C once; B and C never share a study.
    assert edges == {("A", "B"): 1, ("A", "C"): 1}


def test_intrastudy_dedup_and_no_self_loops():
    dsid = _load([make_study(nct_id="N1", conditions=["A", "A", "B"])])
    r = build_network(dsid, node_type="condition")
    weights = {n["label"]: n["weight"] for n in store.NET_RESULTS[r["result_id"]]["nodes"]}
    assert weights["A"] == 1  # duplicate within a study counted once
    edges = store.NET_RESULTS[r["result_id"]]["edges"]
    assert all(e["source"] != e["target"] for e in edges)  # no self-loops


def test_spelling_variants_merge_into_one_node():
    dsid = _load([
        make_study(nct_id="N1", conditions=["Non-Small Cell Lung Cancer"]),
        make_study(nct_id="N2", conditions=["Non Small Cell Lung Cancer"]),
        make_study(nct_id="N3", conditions=["non-small cell lung cancer"]),
    ])
    r = build_network(dsid, node_type="condition")
    nodes = store.NET_RESULTS[r["result_id"]]["nodes"]
    assert len(nodes) == 1            # three spellings collapse to one node
    assert nodes[0]["weight"] == 3


def test_top_n_limits_nodes():
    studies = [make_study(nct_id=f"N{i}", conditions=[f"C{i}"]) for i in range(10)]
    dsid = _load(studies)
    r = build_network(dsid, node_type="condition", top_n=3)
    assert r["num_nodes"] == 3
    assert r["truncated"] is True
