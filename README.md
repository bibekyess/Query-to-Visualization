# ClinicalTrials.gov Query-to-Visualization Agent

An AI-enabled backend that answers natural-language questions about clinical trials
by fetching live data from the ClinicalTrials.gov v2 API and returning a structured
visualization specification — ready for a frontend to render.

---

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (`pip install uv`)
- An OpenAI API key

### Install & Run

```bash
# 1. Clone / unzip into a directory
cd query_to_visualization_agent

# 2. Copy env template and fill in your key
cp .env.example .env
# edit .env: OPENAI_API_KEY=sk-...

# 3. Install dependencies
uv sync

# 4. Start the server
uv run python main.py
# → listening on http://localhost:8000
```

### Make a request

```bash
curl -X POST http://localhost:8000/visualize \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How has the number of pembrolizumab trials changed per year since 2015?",
    "filters": {"drug_name": "pembrolizumab", "start_year": 2015}
  }'
```

Interactive docs: http://localhost:8000/docs

---

## Request Schema

```
POST /visualize
Content-Type: application/json

{
  "query": string (required)          — natural-language question
  "filters": {                        — all optional
    "drug_name":  string              — drug / intervention
    "condition":  string              — disease or condition
    "phase":      string[]            — EARLY_PHASE1 | PHASE1 | PHASE2 | PHASE3 | PHASE4 | NA
    "sponsor":    string              — sponsor name
    "country":    string              — country name
    "start_year": integer             — trials starting from this year
    "end_year":   integer             — trials starting up to this year
    "status":     string              — RECRUITING | COMPLETED | …
  }
}
```

---

## Response Schema

```
{
  "visualization": {
    "type":     string          — bar_chart | time_series | histogram |
                                  scatter | network_graph | grouped_bar
    "title":    string          — human-readable chart title
    "encoding": {               — Vega-Lite-style visual channel mapping
      "x":      {"field": string},
      "y":      {"field": string},
      "series": {"field": string}  (optional, grouped charts)
      // network_graph:
      "nodes":  {"field": string, "weight": string},
      "edges":  {"field": string}
    }
    "data":  [ {<field>: value, "count": int, "citations": [...]} ]
             — null for network_graph (use nodes/edges instead)
    "nodes": [ {"id": string, "label": string, "weight": int} ]
             — network_graph only
    "edges": [ {"source": string, "target": string, "weight": int} ]
             — network_graph only
    "filters": { ...applied filters + "source": "clinicaltrials.gov" }
  },
  "response_metadata": {
    "total_count":         int     — authoritative count from ClinicalTrials.gov
    "fetched_count":       int     — records actually fetched & aggregated
    "time_granularity":    string  — "month" | "year" | null
    "truncated":           bool    — true if total > fetched
    "count_verified":      bool    — true when all records were fetched
    "query_interpretation": string
    "warnings":            string[]
  }
}
```

### Deep Citations

Each data point in `data` carries a `citations` array:

```json
{
  "phase": "Phase 3",
  "count": 41,
  "citations": [
    {
      "nct_id": "NCT04345250",
      "excerpt": "A Phase 3 randomized study evaluating pembrolizumab in combination..."
    }
  ]
}
```

Each `nct_id` links directly to `https://clinicaltrials.gov/study/<nct_id>`.

---

## Project Layout

The `app/` package is organized by layer, so each concern can change independently:

```
app/
  config.py            # pydantic-settings: model, API key, record caps, base URL, turn limit
  main.py              # FastAPI app (HTTP layer)
  models.py            # request/response Pydantic schemas

  prompts/system.md    # the agent's system prompt as editable text (swap without code changes)
  llm/provider.py      # OpenAI wrapper — the single seam to the LLM SDK

  agent/
    loop.py            # tool-calling control loop
    tool_schemas.py    # OpenAI function-calling definitions
    registry.py        # tool name → Python function map

  tools/
    store.py           # in-memory dataset/result handles
    search.py  aggregate.py  network.py  finalize.py   # the four agent tools

  clinicaltrials/
    client.py          # HTTP + pagination + count
    filters.py         # Essie filter.advanced builder
    extractors.py      # field extraction from study records

  viz/selector.py      # deterministic chart-type rules
```

To retune the agent's behavior, edit `prompts/system.md`. To swap LLM providers,
reimplement `llm/provider.py`. To add a new aggregation field, edit `tools/aggregate.py`
plus the `group_by` enum in `agent/tool_schemas.py`.

---

## Architecture & Design Decisions

### Tool-calling agent (not code-gen, not single-plan)

The LLM orchestrates via four typed tools:

| Tool | Purpose |
|------|---------|
| `search_trials` | Fetch + cache matching studies; return `dataset_id` |
| `aggregate` | Group by a field; return `result_id` + group labels |
| `build_network` | Co-occurrence network; return `result_id` + summary |
| `finalize_visualization` | Assemble & return the final spec |

**Key invariant:** the LLM never sees or writes numeric data values. All
counts, buckets, and co-occurrence weights are computed deterministically in
Python. The LLM only handles `dataset_id` / `result_id` references plus
human-readable field name labels.

### Anti-hallucination: no numbers through the LLM

`aggregate` returns `{result_id, groups: [str], num_groups: int}` — labels
only, no counts. `finalize_visualization` looks up the stored result and
inserts the pre-computed data array. The LLM contributes only the title and
encoding labels (axis names).

### Hybrid viz type selection

1. **Deterministic rules** in `app/viz/selector.py` map the `group_by` field shape to
   chart type: time fields → `time_series`, continuous fields → `histogram`,
   default → `bar_chart`.
2. The LLM may pass `viz_hint` to break ties (e.g. `"scatter"`, `"network_graph"`).
   An unrecognised hint is ignored.

### Deep citations: free from aggregation

Because we paginate and aggregate record-by-record (never using the global
`/stats/field/values` endpoint), each bucket already holds the NCT IDs that
contributed to it. Citations fall out of aggregation at zero extra API cost.

### Count verification

For every scoped query, `search_trials` calls `countTotal=true&pageSize=1`
to get an authoritative server-side total. If `fetched_count == total_count`,
`count_verified = true`. If records were truncated (> 5,000 default), a
warning is emitted in `response_metadata`.

### Rate limit safety

The HTTP client retries with exponential back-off on HTTP 429 (up to 4
attempts). Default `max_records = 5,000` limits the per-request page count
to ≤ 5 calls for most queries.

---

## Supported Visualization Types

| Type | Triggered when |
|------|---------------|
| `bar_chart` | Default for categorical distributions |
| `time_series` | `group_by` is `start_year` / `start_month` / `completion_year` |
| `histogram` | `group_by` is `enrollment_bucket` |
| `scatter` | LLM hint `"scatter"` |
| `network_graph` | `build_network` is called |
| `grouped_bar` | LLM hint `"grouped_bar"` |

### Supported `group_by` fields for `aggregate`

`phase` · `status` · `start_year` · `start_month` · `completion_year` ·
`sponsor_name` · `sponsor_class` · `country` · `intervention_type` ·
`study_type` · `condition` · `enrollment_bucket`

---

## Limitations & Future Work

- **Comparison queries** ("Drug A vs Drug B"): the current design supports one
  dataset per request. Side-by-side comparisons would require merging two
  datasets with a `series_by` dimension — feasible but not yet implemented.
- **Scatter plots**: require two continuous fields per study (e.g. enrollment vs
  duration). Currently triggered only by LLM hint; richer auto-detection is a
  next step.
- **In-memory state**: datasets are cached per process with no TTL or eviction.
  Under sustained load a Redis or SQLite backing store would be appropriate.
- **Citation excerpt length**: excerpts are capped at 200 characters from
  `briefSummary`. The full text is available via the single-study endpoint
  (`/studies/{nct_id}`).
- **Records cap**: `max_records` defaults to 5,000. Very broad queries (e.g.
  "all cancer trials") return a representative sample, not the full corpus.
- **No streaming**: the endpoint is synchronous; large datasets (close to
  10,000 records) may take 15–30 seconds.

---

## AI Tools Used

This project was built with **Claude Code** (Anthropic) as the primary coding
assistant. Claude was used to:

- Research and verify the ClinicalTrials.gov v2 API by running live `curl` calls
  (see `CLINICALTRIALS_API_INVESTIGATION.md` for the corrected API reference)
- Design the overall architecture (tool-calling vs code-gen vs pipeline approaches
  were explicitly evaluated and documented)
- Generate the initial implementation of all modules
- Identify and fix bugs (field projection format, `pageToken` vs `nextPageToken`
  asymmetry, lazy OpenAI client initialization)
- Diagnose and fix a TLS fingerprinting issue: `httpx` was blocked with HTTP 403
  by ClinicalTrials.gov despite correct headers. Discovered via live testing that
  the site uses TLS fingerprinting to block non-browser clients; switched the HTTP
  client to Python's built-in `urllib` which uses the OS TLS stack (Windows
  Schannel) and passes through without modification.

**How correctness was validated:**

1. Every API capability was confirmed with a live `curl` before being used in code
   (field projection, Essie filters, `countTotal`, pagination token names).
2. The numeric anti-hallucination invariant was verified structurally: no data
   values pass through the LLM's context — only UUIDs and field name strings.
3. End-to-end tests were run against the live API; 6 real example outputs are
   provided in `examples/` covering every supported visualization type.

The solution was designed deliberately: architecture trade-offs were reasoned
through before writing code (e.g. why tool-calling over a single prompt, why
aggregating from paginated records instead of the stats endpoint, why a hybrid
viz selector rather than pure LLM selection).

---

## Example Runs

Six end-to-end examples are in `examples/`, each containing the full request and
response JSON. To regenerate them: `uv run python tests/run_examples.py`.

| File | Visualization type | Query |
|------|--------------------|-------|
| `01_time_series.json` | `time_series` | Pembrolizumab trials per year since 2015 |
| `02_bar_chart.json` | `bar_chart` | Diabetes trial phase distribution |
| `03_geographic.json` | `bar_chart` (by country) | Countries with the most recruiting breast cancer trials |
| `04_network_graph.json` | `network_graph` | Condition co-occurrence network in lung cancer trials |
| `05_histogram.json` | `histogram` | Enrollment size distribution for Phase 3 cancer trials |
| `06_scatter.json` | `scatter` | Cardiovascular trial counts by sponsor type |
