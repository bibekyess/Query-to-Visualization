"""
Deterministic viz type selection.

Rules are applied in priority order; the LLM's viz_hint only breaks ties for
cases the rules don't cover. This keeps chart selection predictable and prevents
the model from choosing an inappropriate type for time-series or histogram data.
"""

# These group_by values always produce an ordered x-axis that should be rendered as a line chart.
_TIME_FIELDS = {"start_year", "start_month", "completion_year", "completion_month"}

# Enrollment bucket produces ordered size ranges — a histogram, not a bar chart.
_CONTINUOUS_FIELDS = {"enrollment_bucket"}

# Types the categorical aggregate path can honestly produce. Notably excludes
# scatter (needs two continuous variables, not category-vs-count) and grouped_bar
# (needs a second series dimension) — accepting those hints would mislabel a plain
# bar chart. network_graph comes from build_network, handled separately above.
_VALID_TYPES = {"bar_chart", "time_series", "histogram"}


def select(group_by: str, viz_hint: str | None, grouped: bool = False) -> str:
    # Network intent always wins — build_network already chose this path, never override it.
    if viz_hint == "network_graph":
        return "network_graph"

    # Comparison (multi-series) data: a multi-series line for time fields, else grouped bars.
    # grouped_bar is reachable ONLY here, never from a viz_hint.
    if grouped:
        return "time_series" if group_by in _TIME_FIELDS else "grouped_bar"

    # Time fields have inherent ordering; a line chart communicates that better than bars.
    if group_by in _TIME_FIELDS:
        return "time_series"

    # Enrollment buckets are ordered size ranges — histogram is the correct representation.
    if group_by in _CONTINUOUS_FIELDS:
        return "histogram"

    # For everything else, trust the LLM's hint only if it named a type this path
    # can honestly render; otherwise fall through to a bar chart.
    if viz_hint and viz_hint in _VALID_TYPES:
        return viz_hint

    # Default: categorical distribution → bar chart.
    return "bar_chart"
