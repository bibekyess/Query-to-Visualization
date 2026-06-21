"""Essie filter construction for the filter.advanced query parameter."""
from __future__ import annotations

# The agent passes canonical API enum values (PHASE3, EARLY_PHASE1, NA, …), which the
# .upper() fallback below passes straight through. This map only normalizes the shorthand
# forms a manual/REST caller might send ("3", "Phase 3") to those canonical values.
_PHASE_MAP: dict[str, str] = {
    "1": "PHASE1", "phase1": "PHASE1", "phase 1": "PHASE1",
    "2": "PHASE2", "phase2": "PHASE2", "phase 2": "PHASE2",
    "3": "PHASE3", "phase3": "PHASE3", "phase 3": "PHASE3",
    "4": "PHASE4", "phase4": "PHASE4", "phase 4": "PHASE4",
    "early1": "EARLY_PHASE1", "early phase 1": "EARLY_PHASE1",
}


def build_essie(
    phases: list[str] | None,
    start_year: int | None,
    end_year: int | None,
    country: str | None,
) -> str | None:
    """
    Build a filter.advanced Essie expression from structured filters.

    Essie is the ClinicalTrials.gov query language for the filter.advanced parameter.
    Dedicated filter.phase / filter.country params do NOT exist — Essie is the only way.
    Multiple criteria are combined with AND; multiple phases use OR inside parentheses.
    """
    parts: list[str] = []

    if phases:
        phase_exprs = [
            f"AREA[Phase]{_PHASE_MAP.get(p.lower().strip(), p.strip().upper())}"
            for p in phases
        ]
        # Single phase: plain expression.  Multiple: wrap in parentheses for correct OR grouping.
        parts.append(
            phase_exprs[0] if len(phase_exprs) == 1
            else "(" + " OR ".join(phase_exprs) + ")"
        )

    if start_year or end_year:
        # RANGE uses MIN/MAX as open-ended sentinels when one bound is absent.
        start = f"{start_year}-01-01" if start_year else "MIN"
        end = f"{end_year}-12-31" if end_year else "MAX"
        parts.append(f"AREA[StartDate]RANGE[{start},{end}]")

    if country:
        parts.append(f"AREA[LocationCountry]{country}")

    return " AND ".join(parts) if parts else None
