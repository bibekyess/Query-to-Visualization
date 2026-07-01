# ClinicalTrials.gov Query-to-Visualization Agent

An AI backend that answers natural-language questions about clinical trials by
fetching live data from the **ClinicalTrials.gov v2 API** and returning a
structured **visualization specification** (JSON) — ready for a frontend to render.
The backend never renders charts itself.

---

## How to Run

**Prerequisites:** an OpenAI API key. Then set up your env file:

```bash
cp .env.example .env        # then edit .env: OPENAI_API_KEY=sk-...
```

### Option A — Docker (recommended)

```bash
docker compose up -d
```

- API → http://localhost:8000 (web UI at `/`, interactive docs at `/docs`)
- Live logs (Dozzle) → http://localhost:8080/logs

### Option B — Local with [uv](https://github.com/astral-sh/uv)

```bash
uv sync                     # install dependencies (Python 3.11+)
uv run python main.py       # → http://localhost:8000
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

### Web UI

A single-page frontend ships in `app/static/` and is served at the root. It has a
**Query** mode (ask a question, render the live result) and a **Load JSON** mode
(open a bundled `examples/` file or paste a response). Charts render with Vega-Lite,
networks with vis-network; click any data point to see its source-trial citations.

---

## Request / Response Schema

### Request — `POST /visualize`

```
{
  "query": string (required)     — natural-language question
  "filters": {                   — all optional
    "drug_name":  string         — drug / intervention
    "condition":  string         — disease or condition
    "phase":      string[]       — EARLY_PHASE1 | PHASE1 | PHASE2 | PHASE3 | PHASE4 | NA
    "sponsor":    string         — sponsor name
    "country":    string         — country name
    "start_year": integer        — trials starting from this year
    "end_year":   integer        — trials starting up to this year
    "status":     string         — RECRUITING | COMPLETED | …
  }
}
```

### Response

```
{
  "visualization": {             — null when no trials matched (see "message")
    "type":     string           — bar_chart | time_series | histogram | scatter | grouped_bar | network_graph
    "title":    string
    "encoding": {                — Vega-Lite-style channel map
      "x": {"field": string}, "y": {"field": string},
      "series": {"field": string}             (grouped_bar / multi-series time_series)
      "nodes": {...}, "edges": {...}          (network_graph)
    },
    "data":  [ {<field>: value, "count": int, "citations": [...]} ]   — bar/time/histogram/grouped_bar
             [ {"x": num, "y": num, "nct_id": str, "citations": [...]} ] — scatter
             — null for network_graph (use nodes/edges)
    "nodes": [ {"id", "label", "weight"} ]    — network_graph only
    "edges": [ {"source", "target", "weight"} ] — network_graph only
    "filters": { ...applied filters + "source": "clinicaltrials.gov" }
  },
  "message": string | null,      — set only when visualization is null
  "response_metadata": {
    "total_count":   int,        — authoritative server count
    "fetched_count": int,        — records actually fetched & aggregated
    "time_granularity": string,  — "month" | "year" | null
    "truncated":     bool,       — true if total > fetched (sampled)
    "count_verified": bool,      — true when the full corpus was fetched
    "counts_exact":  bool,       — true when bar values are server-authoritative
    "count_server":  int,        — server total, when it differs from fetched
    "query_interpretation": string,
    "warnings": string[]
  }
}
```

### Deep citations

Every datum carries a `citations` array naming the exact field value that placed
the record in its bucket, plus the JSON path it came from — so a citation
substantiates its own bar:

```json
{
  "phase": "Phase 3", "count": 2446,
  "citations": [
    { "nct_id": "NCT04345250", "excerpt": "PHASE3",
      "source_field": "protocolSection.designModule.phases" }
  ]
}
```

Each `nct_id` links to `https://clinicaltrials.gov/study/<nct_id>`. Citations are
capped at 3 per bucket (configurable via `citations_per_group`).

---

## Key Design Decisions & Tradeoffs

**Tool-calling agent (not code-gen, not a single prompt).** The LLM owns language
and control flow only; it orchestrates typed Python tools:

| Tool | Purpose |
|------|---------|
| `search_trials` | Fetch + cache matching studies → `dataset_id` |
| `aggregate` | Group by a field → `result_id` + group labels |
| `aggregate_comparison` | Compare 2+ datasets on a shared field → `result_id` |
| `scatter_points` | Two continuous fields per trial → `result_id` |
| `build_network` | Co-occurrence network → `result_id` |
| `finalize_visualization` | Assemble the final spec (always last) |
| `finalize_notice` | Terminal "no matching trials" response (code-gated) |

- **Anti-hallucination invariant — the LLM never sees or writes a number.** Tools
  share state server-side; the agent passes only `dataset_id` / `result_id` handles
  and human-readable axis labels. All counts, buckets, and weights are computed in
  Python and rebuilt into the response at finalize time. *Tradeoff:* more tool
  round-trips than a single-shot prompt, in exchange for a hard correctness guarantee.

- **Hybrid viz selection.** Deterministic rules in `viz/selector.py` map data shape
  to chart type (time field → `time_series`, enrollment buckets → `histogram`,
  multi-series → `grouped_bar`, else `bar_chart`; scatter/network come from their
  own tools). The LLM's `viz_hint` only breaks ties. *Tradeoff:* less LLM
  flexibility, but predictable, correct chart types.

- **Exact counts even on large result sets.** Aggregating only fetched records is
  biased when a query matches more than the fetch cap. So values are computed by
  tier: (1) full corpus fetched → exact; (2) truncated but enumerable field
  (`phase`, `status`, year, etc.) → a per-bucket `countTotal` query (e.g.
  `AREA[Phase]PHASE3`) makes it exact regardless of size; (3) truncated unbounded
  field (`condition`, `sponsor_name`, `country`) → sampled, flagged
  `counts_exact: false`. *Tradeoff:* a few extra cheap requests for accuracy.

- **Deep citations fall out for free.** Because we paginate and aggregate
  record-by-record (never the global `/stats` endpoint), each bucket already holds
  the NCT IDs that built it — zero extra API cost.

- **Code-gated "no data" response.** A query matching no trials returns
  `visualization: null` + a `message`. This is gated in *code*, not LLM judgment:
  `finalize_notice` is only honored when no search returned data, so a chartable
  query can never be wrongly declined.

- **Network entity normalization.** Node keys are normalized (casing, hyphenation,
  punctuation) so spelling variants collapse into one node; the most common
  original spelling is the display label. Conservative — won't merge synonyms with
  different word order.

- **Rate-limit safety.** The HTTP client (stdlib `urllib`, which passes
  ClinicalTrials.gov's TLS fingerprint check where `httpx` got 403) retries with
  exponential back-off on 429/5xx.

---

## Supported Visualizations

| Type | Triggered when |
|------|---------------|
| `bar_chart` | Default categorical distribution |
| `time_series` | `group_by` is `start_year` / `start_month` / `completion_year` |
| `histogram` | `group_by` is `enrollment_bucket` |
| `grouped_bar` | `aggregate_comparison` over 2+ datasets (date field → multi-series `time_series`) |
| `scatter` | `scatter_points` over two continuous fields (`enrollment`, `duration_days`, `start_year`) |
| `network_graph` | `build_network` (node types: condition, intervention, sponsor, country) |

**`aggregate` `group_by` fields:** `phase` · `status` · `start_year` ·
`start_month` · `completion_year` · `sponsor_name` · `sponsor_class` · `country` ·
`intervention_type` · `study_type` · `condition` · `enrollment_bucket`.

---

## Example Runs

Full request + response JSON for all examples is in **`examples/`** (regenerate with
`uv run python tests/run_examples.py` after starting the server). One in full:

```json
// examples/02_bar_chart.json — "How are diabetes trials distributed across phases?"
{
  "visualization": {
    "type": "bar_chart",
    "title": "Distribution of Diabetes Clinical Trials Across Phases",
    "encoding": { "x": {"field": "phase"}, "y": {"field": "count"} },
    "data": [
      { "phase": "N/A", "count": 9942, "citations": [
        { "nct_id": "NCT04568486", "excerpt": "NA",
          "source_field": "protocolSection.designModule.phases" } ] },
      { "phase": "Phase 2", "count": 2585, "citations": [ /* … */ ] }
      // … more phases
    ],
    "filters": { "condition": "diabetes", "source": "clinicaltrials.gov" }
  },
  "response_metadata": { "total_count": 23959, "counts_exact": true, "warnings": [] }
}
```

| File | Type | Query |
|------|------|-------|
| `01_time_series.json` | `time_series` | Pembrolizumab trials per year since 2015 |
| `02_bar_chart.json` | `bar_chart` | Diabetes trial phase distribution (exact counts) |
| `03_geographic.json` | `bar_chart` | Countries with the most recruiting breast cancer trials |
| `04_network_graph.json` | `network_graph` | Condition co-occurrence in lung cancer trials |
| `05_histogram.json` | `histogram` | Enrollment size distribution, Phase 3 cancer trials |
| `06_sponsor_class.json` | `bar_chart` | Cardiovascular trials by sponsor type |
| `07_comparison_grouped_bar.json` | `grouped_bar` | Pembrolizumab vs nivolumab phases |
| `08_scatter.json` | `scatter` | Enrollment vs trial duration, Phase 3 cancer trials |

---

## Project Layout

```
app/
  config.py          # pydantic-settings (model, API key, record caps, turn limit)
  main.py            # FastAPI app — also serves the web UI + examples
  models.py          # request/response Pydantic schemas
  static/            # bundled single-page web UI
  prompts/system.md  # agent system prompt (editable text — retune without code)
  llm/provider.py    # OpenAI wrapper — the single seam to the LLM SDK
  agent/             # loop.py (control loop), tool_schemas.py, registry.py
  tools/             # search, aggregate, scatter, network, finalize, store
  clinicaltrials/    # client.py (HTTP/pagination), filters.py (Essie), extractors.py
  viz/selector.py    # deterministic chart-type rules
```

To retune behavior, edit `prompts/system.md`; to swap LLM providers, reimplement
`llm/provider.py`; to add an aggregation field, edit `tools/aggregate.py` + the
`group_by` enum in `agent/tool_schemas.py`.

---

## Limitations & What I'd Improve With More Time

**Query coverage**
- *Synonym resolution* — "Keytruda" isn't mapped to "Pembrolizumab"; a curated
  synonym map would broaden coverage (highest-value next step).
- *Within-dataset comparison* — comparing a field *within* one dataset (Phase 2 vs
  Phase 3 of the same set) needs a `series_by` dimension; today each series is its
  own `search_trials` call.
- *Multi-hop & multi-turn* — no query decomposition ("sponsors in both Europe and
  Asia") or conversational follow-ups.

**Data & counts**
- *Unbounded fields* (`condition`/`sponsor_name`/`country`) are sampled when
  truncated (flagged `counts_exact: false`); a two-pass top-N-then-`countTotal`
  refinement would make them exact.

**Performance & scale**
- No result caching (repeat queries re-fetch); in-memory handles have no TTL or
  eviction. A TTL cache / Redis backend would fix both. No streaming, so very broad
  queries can take 15–30s.

**Output quality**
- Network edge weights are raw co-occurrence counts; scaling them into an
  association-strength metric (Jaccard / PMI / per-trial rate) would distinguish
  genuine associations from coincidental ones in large datasets. Dense scatters
  lack binning/trend lines; errors return a text `message` rather than structured
  error codes.
- Nodes carry only degree-based weights; computing graph metrics (betweenness
  centrality, community detection) via NetworkX would surface true hubs and
  clusters — pattern from the [`networkx` skill](https://github.com/K-Dense-AI/scientific-agent-skills) (scientific-agent-skills).

**Coverage**
- Only `GET /studies` is used; adding the single-trial endpoint
  (`GET /studies/{nctId}`) and CSV export would enable a trial "zoom-in"
  (eligibility, contacts, results) and bulk download — both documented in the
  [`clinicaltrials-database` skill](https://github.com/davila7/claude-code-templates/blob/main/cli-tool/components/skills/scientific/clinicaltrials-database/SKILL.md).

**Robustness**
- Field/enum reference is static (could use live `/studies/enums`); no explicit
  schema validate-and-repair step on LLM output; tool-level logging and end-to-end
  integration tests would aid debugging beyond the 58 unit tests.
- LLM-supplied search terms reach the API unsanitized and third-party trial text in
  citations is untagged; input sanitization + provenance flagging would harden the
  data path — per the [`database-lookup` retrieval-contract](https://github.com/K-Dense-AI/scientific-agent-skills) guidance (scientific-agent-skills).

---

## AI Tools Used & Validation

Built with **Claude Code** (Anthropic). Claude verified the ClinicalTrials.gov API
with live `curl` calls (see `CLINICALTRIALS_API_INVESTIGATION.md`), evaluated the
architecture tradeoffs, generated the implementation, and diagnosed bugs — notably
the TLS-fingerprinting `403` that forced the switch from `httpx` to stdlib `urllib`.

**Correctness was validated by:**
1. Confirming every API capability with a live `curl` before coding it.
2. Enforcing the anti-hallucination invariant structurally (no numbers in LLM context).
3. A 58-test offline suite (`uv run pytest`) over the deterministic core —
   extractors, Essie filters, viz selector, both count tiers, comparison, scatter,
   network co-occurrence, and the code-gated "no data" path.
4. Spot-checking exact counts against the live API (e.g. diabetes Phase 3 = 2,446).
5. Generating the 8 `examples/` end-to-end, covering every visualization type.
