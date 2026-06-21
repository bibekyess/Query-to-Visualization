"""Tool 3: build_network — build a co-occurrence network from fetched studies."""
from __future__ import annotations

import re
import uuid
from collections import Counter

from app.clinicaltrials import extractors as ct
from app.tools.store import DATASETS, NET_RESULTS


def _norm_key(label: str) -> str:
    """
    Collapse spelling variants of the same entity to one key.

    Condition/intervention names arrive with inconsistent casing, hyphenation and
    punctuation (e.g. "Non-small Cell Lung Cancer", "Non Small Cell Lung Cancer",
    "Non-Small Cell Lung Cancer"). Lowercasing and reducing every run of
    non-alphanumeric characters to a single space merges those into one node so
    the graph isn't fragmented across near-duplicates. (This is deliberately
    conservative — it won't merge true synonyms with different word order.)
    """
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


def _network_entities(study: dict, node_type: str) -> list[str]:
    # Returns entity names for a single study; these become network nodes.
    if node_type == "condition":
        return ct.extract_conditions(study)[:5]
    if node_type == "intervention":
        return [iv.get("name", "") for iv in ct.extract_interventions(study) if iv.get("name")][:5]
    if node_type == "sponsor":
        return [ct.extract_sponsor_name(study)]
    if node_type == "country":
        return ct.extract_countries(study)
    return []


def build_network(
    dataset_id: str,
    node_type: str = "condition",
    top_n: int = 25,
) -> dict:
    """
    Build a co-occurrence network: two entities are connected if they appear
    in the same study. Edge weight = number of studies they share.
    """
    if dataset_id not in DATASETS:
        return {"error": f"Dataset {dataset_id!r} not found. Call search_trials first."}

    studies = DATASETS[dataset_id]
    node_counts: Counter[str] = Counter()           # normalized key → studies mentioning it
    edge_counts: Counter[tuple[str, str]] = Counter()
    # For each normalized key, track how often each original spelling appears so we can
    # show the most common human-readable label rather than the normalized form.
    display: dict[str, Counter[str]] = {}

    for study in studies:
        # Normalize then deduplicate within a study, so spelling variants don't create
        # self-loops or duplicate edges. Cap at 10 to bound the pair explosion
        # (10 entities → at most 45 pairs; without the cap one study could generate thousands).
        keys: list[str] = []
        for raw in _network_entities(study, node_type):
            key = _norm_key(raw)
            if not key or key in keys:
                continue
            keys.append(key)
            display.setdefault(key, Counter())[raw] += 1
        keys = keys[:10]
        for k in keys:
            node_counts[k] += 1
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = sorted([keys[i], keys[j]])   # canonical key order for the edge
                edge_counts[(a, b)] += 1

    def _label(key: str) -> str:
        return display[key].most_common(1)[0][0]

    # Keep only the most-mentioned nodes; everything else would be noise in a visualisation.
    top_nodes = [n for n, _ in node_counts.most_common(top_n)]
    top_set = set(top_nodes)

    # id = normalized key (stable, what edges reference); label = prettiest original spelling.
    nodes = [{"id": n, "label": _label(n), "weight": node_counts[n]} for n in top_nodes]
    # Keep only edges whose both endpoints made the top-N cut, then cap total edges.
    edges = [
        {"source": a, "target": b, "weight": w}
        for (a, b), w in sorted(edge_counts.items(), key=lambda x: x[1], reverse=True)
        if a in top_set and b in top_set
    ][:150]

    result_id = str(uuid.uuid4())
    NET_RESULTS[result_id] = {
        "nodes": nodes,
        "edges": edges,
        "node_type": node_type,
        "dataset_id": dataset_id,
        "truncated": len(node_counts) > top_n,
        "total_nodes": len(node_counts),
    }

    return {
        "result_id": result_id,
        "num_nodes": len(nodes),
        "num_edges": len(edges),
        "top_node_labels": [n["label"] for n in nodes[:5]],
        "truncated": len(node_counts) > top_n,
        "total_nodes_in_data": len(node_counts),
    }
