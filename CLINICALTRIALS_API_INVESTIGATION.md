# ClinicalTrials.gov v2 Data API — Verified Reference

**API Base URL:** `https://clinicaltrials.gov/api/v2`
**Docs:** https://clinicaltrials.gov/data-api/api
**Last verified:** 2026-06-21 (via live API calls)
**Auth:** None required.

> **Status of this document:** Every capability below was confirmed with a real
> live API call. An earlier draft of this file concluded the API had "no field
> projection, no aggregation, and only `filter.overallStatus` filtering" — **all
> three of those conclusions were wrong**, caused by testing invented parameter
> names. They have been corrected here. See §8 for the corrections.

---

## 1. Search endpoint — `GET /studies`

### Working query parameters (verified)

| Parameter | Purpose | Example |
|---|---|---|
| `query.cond` | Condition / disease (free text) | `query.cond=diabetes` |
| `query.intr` | Intervention / drug (free text) | `query.intr=pembrolizumab` |
| `query.term` | General full-text search | `query.term=cancer` |
| `query.locn` | Location (free text) | `query.locn=Boston` |
| `query.spons` | Sponsor / collaborator (free text) | `query.spons=Pfizer` |
| `filter.overallStatus` | Status enum(s), comma-separated | `filter.overallStatus=RECRUITING` |
| `filter.ids` | NCT ID intersection, comma-separated | `filter.ids=NCT04852770,NCT01728545` |
| **`filter.advanced`** | **Essie expression — the real structured filter** | `filter.advanced=AREA[Phase]PHASE3` |
| `filter.geo` | Geographic distance filter | `filter.geo=distance(39.0,-77.0,100mi)` |
| `fields` | **Field projection** (PascalCase OR dotted path) | `fields=NCTId,Phase,OverallStatus` |
| `sort` | Result ordering | `sort=StartDate:desc` |
| `pageSize` | Results per page, **max 1000** | `pageSize=1000` |
| `pageToken` | Pagination cursor (REQUEST param) | `pageToken=<token>` |
| `countTotal` | Include `totalCount` in response | `countTotal=true` |
| `format` | `json` (default) or `csv` | `format=json` |

### Parameters that do NOT exist (return HTTP 400)

`filter.phase`, `filter.country`, `filter.studyType`, `filter.sponsor`,
`filter.date*`, `aggFilters`. **Phase / date / condition structured filtering is
done via `filter.advanced` Essie expressions, not dedicated `filter.*` params.**

---

## 2. `filter.advanced` — Essie expressions (the primary structured filter)

This is the key narrowing mechanism. Syntax: `AREA[<FieldName>]<expression>`.

| Goal | Essie expression | Verified effect |
|---|---|---|
| Phase = 3 | `AREA[Phase]PHASE3` | diabetes: 23,959 → **2,446** |
| Start date range | `AREA[StartDate]RANGE[2015-01-01,MAX]` | narrows by start date |
| Condition (alt to query.cond) | `AREA[Condition]diabetes` | works on `/studies` |

URL-encode the brackets: `%5B` = `[`, `%5D` = `]`.
Multiple criteria can be combined within the Essie expression.

**Verified example (Phase 3 narrowing):**
```bash
curl "https://clinicaltrials.gov/api/v2/studies?query.cond=diabetes&filter.advanced=AREA%5BPhase%5DPHASE3&countTotal=true&pageSize=1"
# → totalCount: 2446   (vs 23959 unfiltered for diabetes)
```

---

## 3. `fields=` projection — VERIFIED WORKING (both token formats)

Both styles return HTTP 200 with a reduced payload (~10× smaller):

- **PascalCase field names:** `fields=NCTId,BriefTitle,Phase,OverallStatus`
- **Dotted JSON paths:** `fields=protocolSection.identificationModule.nctId,protocolSection.designModule.phases`

Use projection on every paginated fetch to cut bandwidth. Always include the
fields you need for aggregation **and** for citations (NCT ID + the excerpt source field).

---

## 4. `/stats/field/values` — GLOBAL aggregation only (NOT scopable)

`GET /stats/field/values?fields=Phase` returns **per-value counts across the
entire database** — but it **rejects all scoping parameters** (`query.cond`,
`filter.advanced` → HTTP 400 "Invalid prefix in parameter name"). It accepts
only `fields`.

```bash
curl "https://clinicaltrials.gov/api/v2/stats/field/values?fields=Phase"
# → [{"piece":"Phase","topValues":[
#      {"value":"NA","studiesCount":229977},
#      {"value":"PHASE2","studiesCount":88939},
#      {"value":"PHASE3","studiesCount":49268}, ...]}]
```

**Implication:** This endpoint gives *global* facet counts only. It **cannot**
produce a distribution for a specific condition/drug, and it returns **no NCT
IDs** (so it cannot support deep citations). It is useful only for global context.

Other stats endpoints: `GET /stats/size` (global totals + size percentiles).

### The real per-query count guardrail: `countTotal=true`

For an authoritative server-side count of any **scoped** query, add
`countTotal=true&pageSize=1` to a `/studies` search. This is what we use to
cross-check our client-side aggregation (see §7).

```bash
curl "https://clinicaltrials.gov/api/v2/studies?query.cond=diabetes&filter.advanced=AREA%5BPhase%5DPHASE3&countTotal=true&pageSize=1"
# → totalCount: 2446   (authoritative; compare against our client-side count)
```

---

## 5. Pagination

- **Max `pageSize` = 1000** (verified: a `pageSize=1000` request returned exactly 1000 studies).
- Response includes **`nextPageToken`** when more pages exist (absent on last page).
- Send it back as the **`pageToken`** request parameter for the next page.
- ⚠️ **Asymmetry:** read `nextPageToken` from the response, send `pageToken` in the request. (Both skill docs had this backwards in their pagination examples; corrected.)

```python
page_token = None
while True:
    params = {"query.cond": "cancer", "pageSize": 1000}
    if page_token:
        params["pageToken"] = page_token            # request param
    data = requests.get(BASE + "/studies", params=params).json()
    all_studies.extend(data["studies"])
    page_token = data.get("nextPageToken")           # response field
    if not page_token:
        break
```

---

## 6. Field paths & controlled values

All study fields are nested under `protocolSection` (some derived data under `derivedSection`).

| Field | JSON path |
|---|---|
| NCT ID | `protocolSection.identificationModule.nctId` |
| Brief title | `protocolSection.identificationModule.briefTitle` |
| Official title | `protocolSection.identificationModule.officialTitle` |
| Overall status | `protocolSection.statusModule.overallStatus` |
| Start date | `protocolSection.statusModule.startDateStruct.date` (`YYYY-MM-DD` / `YYYY-MM` / `YYYY`) |
| Completion date | `protocolSection.statusModule.completionDateStruct.date` |
| Phase(s) | `protocolSection.designModule.phases` (array) |
| Study type | `protocolSection.designModule.studyType` |
| Enrollment | `protocolSection.designModule.enrollmentInfo.count` (`.type` = ACTUAL/ESTIMATED) |
| Lead sponsor name | `protocolSection.sponsorCollaboratorsModule.leadSponsor.name` |
| Lead sponsor class | `protocolSection.sponsorCollaboratorsModule.leadSponsor.class` |
| Conditions | `protocolSection.conditionsModule.conditions` (array) |
| Interventions | `protocolSection.armsInterventionsModule.interventions` (array of `{type,name,description}`) |
| Locations / country | `protocolSection.contactsLocationsModule.locations[].country` (+ `city`, `state`, `facility`, `geoPoint`) |
| Brief summary (citation text) | `protocolSection.descriptionModule.briefSummary` |
| Eligibility criteria (citation text) | `protocolSection.eligibilityModule.eligibilityCriteria` |

### Enums

- **Phase:** `EARLY_PHASE1`, `PHASE1`, `PHASE2`, `PHASE3`, `PHASE4`, `NA` (array; may be empty)
- **Overall status:** `RECRUITING`, `NOT_YET_RECRUITING`, `ENROLLING_BY_INVITATION`, `ACTIVE_NOT_RECRUITING`, `SUSPENDED`, `TERMINATED`, `COMPLETED`, `WITHDRAWN`, `UNKNOWN`
- **Sponsor class:** `INDUSTRY`, `OTHER`, `FED`, `NIH`, `NETWORK`
- **Intervention type:** `DRUG`, `BIOLOGICAL`, `DEVICE`, `PROCEDURE`, `RADIATION`, `BEHAVIORAL`, `DIETARY_SUPPLEMENT`, `GENETIC`, `DIAGNOSTIC_TEST`, `COMBINATION_PRODUCT`, `OTHER`
- **Study type:** `INTERVENTIONAL`, `OBSERVATIONAL`, `EXPANDED_ACCESS`

---

## 7. Implications for the query-to-visualization backend

1. **Push filters server-side via `filter.advanced` (Essie).** Phase, date ranges,
   conditions — narrow before fetching. A specific query then returns hundreds,
   not tens of thousands, of records.

2. **Always use `fields=` projection + `pageSize=1000`** on paginated fetches. This
   makes the "fetch all matching → aggregate in Python" path cheap and viable.

3. **Aggregate client-side (deterministic Python), not in the LLM.** Counts,
   year-bucketing, phase distributions, and co-occurrence/network edges are
   computed in code over the fetched records — never generated by the model.

4. **Deep citations require record-level data.** Because the stats endpoint
   exposes no NCT IDs, citations must come from the paginated records. The
   aggregator collects `nct_id` + an excerpt (e.g. `briefSummary`) per datum as
   it groups — citations fall out of aggregation for free.

5. **Anti-hallucination guardrail: reconcile against `countTotal=true`.** For each
   scoped group, an authoritative server-side count is one cheap call
   (`countTotal=true&pageSize=1`). Compare it to our client-side count; match →
   high confidence, mismatch → flag in `response_metadata`. (The global
   `/stats/field/values` endpoint is NOT usable for this — it can't be scoped.)

6. **Rate limit ≈ 50 requests / minute per IP.** HTTP 429 on exceed. Add
   exponential backoff and cache responses (keyed by query) to stay polite and
   fast during demos.

---

## 8. Corrections to the earlier draft

| Earlier (wrong) claim | Reality (verified) |
|---|---|
| "No `fields=` projection" | Works in both PascalCase and dotted-path forms |
| "No server-side aggregation" | `/stats/field/values` returns global per-value counts (not scopable) |
| "Only `filter.overallStatus` works" | `filter.advanced` (Essie), `filter.ids`, `filter.geo` also work |
| "`filter.phase` works" (skill docs) | `filter.phase` returns HTTP 400 — use `AREA[Phase]PHASE3` instead |
| "Max `pageSize` = 100" | Max is 1000 (the earlier test never tried above 100) |
| Response key `pageToken` (skill docs) | Response key is `nextPageToken`; `pageToken` is the request param |

---

## 9. Quick reference — sample calls

```bash
# Condition search with total count
curl "https://clinicaltrials.gov/api/v2/studies?query.cond=diabetes&countTotal=true&pageSize=1"

# Drug + Phase 3 + started since 2015, projected fields, full page
curl "https://clinicaltrials.gov/api/v2/studies?query.intr=pembrolizumab&filter.advanced=AREA%5BPhase%5DPHASE3%20AND%20AREA%5BStartDate%5DRANGE%5B2015-01-01,MAX%5D&fields=NCTId,Phase,StartDate,BriefTitle&pageSize=1000&countTotal=true"

# Single study detail
curl "https://clinicaltrials.gov/api/v2/studies/NCT01234567"

# Global phase facet (context only; not scopable, no NCT IDs)
curl "https://clinicaltrials.gov/api/v2/stats/field/values?fields=Phase"
```
