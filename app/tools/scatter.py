"""Tool: scatter_points — build (x, y) points from two continuous per-study fields.

Unlike aggregate (category → count), scatter plots one point per study using two
continuous variables (e.g. enrollment vs trial duration). Coordinates and citations
are computed in Python; the LLM only receives the result_id and a point count.
"""
from __future__ import annotations

import uuid

from app.clinicaltrials import extractors as ct
from app.tools.store import DATASETS, DATASET_META, SCATTER_RESULTS

# field name → (extractor, JSON source path for citations)
_FIELDS: dict[str, tuple] = {
    "enrollment": (
        ct.extract_enrollment,
        "protocolSection.designModule.enrollmentInfo.count",
    ),
    "duration_days": (
        ct.extract_duration_days,
        "protocolSection.statusModule.completionDateStruct.date − startDateStruct.date",
    ),
    "start_year": (
        ct.extract_start_year,
        "protocolSection.statusModule.startDateStruct.date",
    ),
}


def scatter_points(
    dataset_id: str,
    x_field: str,
    y_field: str,
    max_points: int = 500,
) -> dict:
    """
    Build scatter points from two continuous fields, one point per study that has
    both values present. Stores the points server-side and returns only a handle
    and a point count — coordinate values never enter the LLM context.
    """
    if dataset_id not in DATASETS:
        return {"error": f"Dataset {dataset_id!r} not found. Call search_trials first."}
    if x_field not in _FIELDS or y_field not in _FIELDS:
        return {"error": f"Unsupported field. Choose two of: {sorted(_FIELDS)}"}

    x_fn, x_src = _FIELDS[x_field]
    y_fn, y_src = _FIELDS[y_field]

    points: list[dict] = []
    for study in DATASETS[dataset_id]:
        vx = x_fn(study)
        vy = y_fn(study)
        if vx is None or vy is None:
            continue   # a point needs both coordinates
        nct_id = ct.extract_nct_id(study)
        points.append({
            "x": vx,
            "y": vy,
            "nct_id": nct_id,
            "citations": [{
                "nct_id": nct_id,
                "excerpt": f"{x_field}={vx}; {y_field}={vy}",
                "source_field": f"{x_src}; {y_src}",
            }],
        })

    capped = points[:max_points]
    result_id = str(uuid.uuid4())
    SCATTER_RESULTS[result_id] = {
        "points": capped,
        "x_field": x_field,
        "y_field": y_field,
        "dataset_id": dataset_id,
        "total_points": len(points),
        "truncated": len(points) > len(capped),
    }

    return {
        "result_id": result_id,
        "num_points": len(capped),
        "x_field": x_field,
        "y_field": y_field,
    }
