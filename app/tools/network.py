"""Tool 3: build_network — build a co-occurrence network from fetched studies."""
from __future__ import annotations

import uuid
from collections import Counter

from app.clinicaltrials import extractors as ct
from app.tools.store import DATASETS, NET_RESULTS


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
    node_counts: Counter[str] = Counter()
    edge_counts: Counter[tuple[str, str]] = Counter()

    for study in studies:
        # Deduplicate within a study (a study shouldn't create self-loops or duplicate edges).
        # Cap at 10 to prevent combinatorial explosion on studies with many entities
        # (10 entities → at most 45 pairs; without the cap one study could generate thousands).
        entities = list(set(_network_entities(study, node_type)))[:10]
        for e in entities:
            node_counts[e] += 1
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                # Sort the pair so (A, B) and (B, A) map to the same counter key.
                a, b = sorted([entities[i], entities[j]])
                edge_counts[(a, b)] += 1

    # Keep only the most-mentioned nodes; everything else would be noise in a visualisation.
    top_nodes = [n for n, _ in node_counts.most_common(top_n)]
    top_set = set(top_nodes)

    nodes = [{"id": n, "label": n, "weight": node_counts[n]} for n in top_nodes]
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
