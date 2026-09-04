# AI Logistics Analytics Platform — Task Breakdown

**Parallel Execution Plan.** Derived from PRD v2.0. This supersedes the earlier sequential 7-block breakdown: same scope, reorganized so multiple workers (people or parallel agents) can build simultaneously without blocking each other.

| Document | Value |
|---|---|
| Source PRD | v2.0 |
| Effort (sum of all tasks) | **~13h35m** — above the source spec's 6–10h guidance. Parallelizing cuts wall-clock, not effort; see "If short on time". |
| Wall-clock if parallelized | **~6h** with 3–4 workers (Wave 0 45m → longest Wave 1 stream, C at 3h15m → Wave 2 1h15m → Wave 3 45m) |
| Status | Wave 0 + Streams A/B1/B2/D/E/G + Wave 2 (incl. I.6) complete — contracts, fixtures, routers, backend tests, frontend dashboard + Ask Operations (ports: FE 3001, BE 8080), reconciliation tests, and fail-open Langfuse tracing all landed. Backend code is grouped under `backend/api`, `backend/agents`, `backend/tools`, `backend/observe`, and `backend/core`. Ask Operations supports server-held follow-up threads via `thread_id`, with a stateless `history` fallback capped at 10 turns; the UI limit is also 10 turns. Current backend collection: 344 tests. |
| Dataset | `mock_logistics_data.csv` (400 rows, 2025-01-01 to 2025-12-30, 1 row = 1 order) |
| Ground-truth KPI values | Total Orders 400 · Delivered Orders 359 · Delayed Orders 55 · On-Time Rate 84.68% · Delay Rate 15.32% · Avg Delivery Time 3.83 days |

## How parallelization works here

The thing that normally forces this project to be serial is that the frontend waits for the API, the AI orchestrator waits for the Query Tool, and everything waits for ingestion. **Wave 0 removed that by freezing the data contracts up front** (done — see `backend/core/schemas.py`). After Wave 0, every stream codes against a contract and a fixture — not against another stream's unfinished code. Streams integrate in Wave 2 by deleting their stubs.

Rule for every stream: **never edit a file another stream owns.** The file-ownership map at the end is the conflict-avoidance mechanism. Shared files (`main.py`, `schemas.py`) are written once in Wave 0 and then treated as read-only until Wave 2.

```
WAVE 0 (serial, blocking, ~45m)
  contracts + repo skeleton + fixtures
        |
        +----------+----------+----------+----------+----------+
        |          |          |          |          |          |
      A: Auth   B1: Data   B2: Query  C: Front-  D: Fore-   E: Orches-   F: Deploy
      (~10m)    +Metrics    Tool      end/Dash   cast       trator       scaffold
                 (~55m)     (~55m)    (~3h15m)   (~1h30m)   (~2h20m)     (~45m)
      G: Langfuse traceability (~1h15m)
        |          |          |          |          |          |          |
        +----------+----------+----------+----------+----------+----------+
                                    |
                          WAVE 2 (integration, ~1h)
                          swap stubs for real modules
                                    |
                          WAVE 3 (deploy + README, ~45m)
```

---

## WAVE 0 — Contracts & Skeleton (serial, blocking, ~45 min)

*One worker does this alone. Nothing else starts until it lands. Everything here goes into files that are then frozen.*

- [x] **W0.1** (10 min) Repo skeleton: `backend/` (FastAPI) + `frontend/` (React/Next). One `backend/main.py` imports and registers routers from `backend/api/` — `auth.py`, `query.py`, `ask.py`, and `forecast.py`.
- [x] **W0.2** (20 min) Write `backend/core/schemas.py` with the five contracts below, as Pydantic models. This file is frozen after Wave 0.
- [x] **W0.3** (10 min) Write `backend/core/fixtures.py`: one hardcoded sample of each contract's response shape (a fake carrier delay-rate result, a fake forecast result, a fake explainability payload). Streams C and E build against these until Wave 2.
- [x] **W0.4** (5 min) `.env.example` with the current auth, LLM, dataset, CORS, narration, and optional Langfuse variables. Commit no credentials.

### The five frozen contracts

**1. StructuredRequest** — what the LLM emits and the tools consume. An `operation` discriminator carries both shapes; without it a forecast horizon has no way to travel from the question to the Forecast Tool.

`operation: "query"`:
```json
{
  "operation": "query",
  "metric": "delay_rate",
  "dimensions": ["carrier"],
  "filters": [{"field": "region", "op": "in", "value": ["US-E", "US-W"]}],
  "time_range": {"preset": "previous_month"},
  "sort": {"by": "delay_rate", "direction": "desc"},
  "limit": 10,
  "visualization": "auto"
}
```

`operation: "forecast"`:
```json
{
  "operation": "forecast",
  "metric": "order_demand",
  "grain": "week",
  "horizon_weeks": 4,
  "filters": [],
  "time_range": null,
  "visualization": "auto"
}
```

- `time_range` is `{"preset": "..."}` or `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`. Allowed metrics/dimensions/operators per PRD §8 + Appendix A.
- `horizon_weeks` is bounded **1–8**; out-of-range is rejected, not clamped.
- `grain` is `"week"` for MVP — daily forecasting is unsupported (400 orders over 365 days is too sparse).
- **For a forecast, `time_range` means the history window to learn from, not the period to report** (`null` = all history, the expected case). Label it explicitly wherever it's displayed so it isn't read as a query filter.

**2. QueryResult** — what the Query Tool returns
```json
{
  "columns": ["carrier", "delay_rate"],
  "rows": [["UPS", 50.0], ["USPS", 25.0]],
  "row_count": 6,
  "metric": "delay_rate",
  "resolved_time_range": {"start": "2025-11-01", "end": "2025-11-30"},
  "truncated": false
}
```

**3. ForecastResult** — what the Forecast Tool returns
```json
{
  "target": "order_demand",
  "grain": "week",
  "horizon_weeks": 4,
  "history": [{"period": "2025-W52", "value": 8}],
  "history_window": {"start": "2025-01-06", "end": "2025-12-28", "observations": 51},
  "forecast": [{"period": "2026-W01", "value": 9.2}],
  "method": "linear_trend_12w",
  "methodology_note": "12-week trend over 51 complete weeks of order history.",
  "recommendation": {
    "rule": "F > B x 1.10 -> increase capacity by ceil(F - B); F < B x 0.90 -> no increase; else hold",
    "baseline_weekly_orders": 7.5,
    "forecast_level": 8.9,
    "delta_orders_per_week": 2,
    "action": "increase_capacity",
    "text": "Forecast averages 8.9 orders/week vs a trailing-4-week baseline of 7.5 (+18.7%), above the 10% threshold - consider capacity for ~2 more orders/week."
  },
  "insufficient_data": false,
  "insufficient_data_reason": null
}
```
`baseline_weekly_orders`, `forecast_level`, `delta_orders_per_week` and `action` are computed by the Forecast Tool — the LLM only relays them. `insufficient_data` is `true` when history has fewer than **8 complete weeks**.

**4. Explainability** — attached to every AI answer
```json
{
  "question": "Which carrier has the highest delay rate?",
  "structured_request": { "...contract 1..." },
  "metric_definition": "delayed orders / delivered orders x 100",
  "metric_basis": {"row_count": 359, "inclusion_rule": "status in (delivered, delayed); exception excluded"},
  "resolved_filters": { "time_range": {"start": "...", "end": "...", "means": "reported_period"}, "filters": [] },
  "query_plan": "group by carrier -> compute delay_rate -> sort desc -> limit 1",
  "result_preview": { "...contract 2..." },
  "forecast_details": null
}
```

For `operation: "forecast"` answers, `query_plan` is not enough to make the result reproducible — populate `forecast_details` and set `resolved_filters.time_range.means` to `"history_window"`:
```json
"forecast_details": {
  "horizon_weeks": 4,
  "method": "linear_trend_12w",
  "history_window": {"start": "2025-01-06", "end": "2025-12-28", "observations": 51},
  "baseline_weekly_orders": 7.5,
  "forecast_level": 8.9,
  "recommendation_rule": "F > B x 1.10 -> increase capacity by ceil(F - B)",
  "insufficient_data": false
}
```
`metric_basis.row_count` exists so the Average Delivery Time denominator (370, includes `exception`) is visibly different from Delivered Orders (359, excludes it) rather than looking like an error — see PRD §8.

**5. AskResponse** — the Ask Operations endpoint's response
```json
{
  "answer": "UPS has the highest delay rate at 50.0%.",
  "chart": { "type": "bar", "x": "carrier", "y": "delay_rate", "data": [] },
  "table": { "...contract 2..." },
  "explainability": { "...contract 4..." },
  "unsupported": false,
  "unsupported_reason": null
}
```

**Exit check:** all four router stubs import cleanly, `schemas.py` validates each example above, fixtures return valid instances. Now fan out.

---

## WAVE 1 — Parallel Streams

*All seven streams below start at the same time. Each owns its own files.*

### Stream A — Auth: HTTP Basic (~10 min, no dependencies)

- [x] **A.1** (7 min) `backend/api/auth.py` (currently a stub): `fastapi.security.HTTPBasic` dependency reading `APP_USERNAME`/`APP_PASSWORD` from env, compared with `secrets.compare_digest` (not `==`). Apply it to every protected router. No login page, no cookie, no user table, no session store.
- [x] **A.2** (3 min) Remove the unused `SESSION_SECRET` line from `.env.example`; Basic Auth uses only `APP_USERNAME` and `APP_PASSWORD`, and credential values remain outside the repository.

**Done when:** protected routes return 401 without credentials and pass with them. *(FR-16)*

*Basic Auth sends credentials on every request, so the deployment must be HTTPS — every host in F.1 terminates TLS by default, so this costs nothing. Tradeoff accepted: a browser prompt is less polished than a styled login page, but it is 10 minutes instead of 45 and removes cookie-signing as a failure surface entirely.*

### Stream B1 — Ingestion + Semantic Metrics (~55 min, critical path)

*Highest-value stream — Data Correctness is 20% of the grade. Assign your strongest worker here.*

- [x] **B1.1** (10 min) Add `pandas` to `pyproject.toml`, then `backend/core/ingestion.py`: `pd.read_csv` with explicit `parse_dates=['order_date','delivery_date']`. Load once at import; never mutate the DataFrame — that is the whole of NFR-02, no read-only mode to configure. **No DuckDB**: 400 rows is not an analytical-database workload.
- [x] **B1.2** (10 min) Column validation: fail loudly with a clear message if any required column is missing. Defensive duplicate-`order_id` check.
- [x] **B1.3** (10 min) `backend/core/status_rules.py`: encode status semantics **once** — `delivered`+`delayed` = Delivered Orders; `exception` separate; `in_transit`/`canceled` excluded. Every metric reads from here.
- [x] **B1.4** (25 min) `backend/core/metrics.py`: the seven metrics per PRD §8 as a registry — `{metric_name: {compute, definition_text, inclusion_rule, basis_count, allowed_dimensions}}`. Explainability reads the definition and population from this registry.

**Done when:** metrics with no filters reproduce the ground-truth values exactly (400 / 359 / 55 / 84.68% / 15.32% / 3.83).

#### Semantic metric decisions and rationale

The following decisions are part of the governed metric contract. Stream B2
must enforce them during request validation, while Streams C and E must preserve
their meaning when displaying or explaining results.

##### 1. `status` is not an approved dimension for status-derived metrics

`status` must not be used as a grouping dimension for `delay_rate`,
`on_time_rate`, `delivered_orders`, or `delayed_orders`. It remains an approved
filter field for those metrics.

Rationale:

- Grouping a status-derived **rate** by `status` is mathematically degenerate.
  Each group contains only one status, so the result collapses to `100%`, `0%`,
  or an undefined rate rather than communicating operational performance.
- For the two count metrics, the issue is redundancy and misleading semantics
  rather than a literal `0%`/`100%` outcome. `delayed_orders` grouped by status
  can only have a positive value in the `delayed` group, while
  `delivered_orders` merely decomposes its already-defined
  `delivered` + `delayed` population.
- Disallowing this combination prevents technically valid but analytically
  meaningless requests from reaching computation, consistent with FR-12.
- A status distribution is still available through `total_orders` grouped by
  `status`. This expresses the intended question directly without changing the
  meaning of a status-derived KPI.
- `status` remains usable as a filter because questions such as “total orders
  with delayed status” or a carrier comparison restricted to completed orders
  are meaningful. Filtering and grouping are separate capabilities and should
  not share the same allow-list blindly.

Implementation rule: the metric registry owns `allowed_dimensions`; the Query
Tool rejects an unapproved metric/dimension combination before grouping. The
global `DimensionName` contract only validates that `status` is a known
dimension—it does not grant every metric permission to use it.

##### 2. A rate with an empty denominator is `None`, not zero

`delay_rate` and `on_time_rate` return Python `None` (JSON `null`) when their
delivered-order denominator is zero. They must not coalesce an undefined result
to `0%`.

Rationale:

- `0%` is a real measurement: the denominator is positive and the numerator is
  zero. For example, `delay_rate = 0%` means completed deliveries exist and none
  were delayed.
- `null` means the metric cannot be calculated because no delivered-order
  population exists. Presenting that case as `0%` would falsely imply measured
  performance instead of absence of evidence.
- The distinction is necessary for trustworthy dashboard, AI-answer, and
  explainability behavior. It prevents “no data” from being described as either
  perfect or poor performance.
- `QueryResult` already permits `None` in row values, so the undefined value can
  travel through the frozen contract without a sentinel number or string.
- `Average Delivery Time` follows the same absence-of-population principle: it
  returns `None` when there are no rows with a usable delivery date.

Required downstream behavior:

- Metric computation checks the denominator explicitly and returns `None` when
  it is zero; do not use `fillna(0)` or another zero fallback.
- The UI renders `null` as `N/A` or “No data”, never `0%`.
- The AI answer must describe the metric as unavailable due to no qualifying
  orders and must not invent or verbalize a zero value.
- Sorting places null metric values last so an undefined group cannot appear as
  the best or worst performer.
- Keep three states distinct: a valid `0.0%`, an aggregate/group whose metric is
  `null`, and a query returning zero rows (the empty-result state from C.7).

### Stream B2 — Query Tool + Validation (~55 min)

*Builds against the metric-registry interface from Wave 0, using a 2-metric stub registry until B1 lands. Integrates in Wave 2.*

- [x] **B2.1** (20 min) `backend/tools/query.py`: compile a StructuredRequest into pandas operations — boolean-mask filters, then complete `groupby` iteration so each metric receives every source column it may need. With no SQL anywhere there is no injection surface to defend, which is the point.
- [x] **B2.2** (20 min) Validation layer: `operation` is one of `query`/`forecast`, metric exists, dimensions allowed for that metric, filter fields/operators allow-listed, limit bounded, and for forecasts `horizon_weeks` is an integer in **1–8** (reject out-of-range, don't clamp) with `grain == "week"`. Reject before computation with a clear error. *(FR-12)*
- [x] **B2.3** (10 min) Time-preset resolver: `previous_month`, `previous_week`, `last_N_weeks`, `last_N_months`, explicit range → concrete start/end dates.
- [x] **B2.4** (5 min) `backend/api/query.py`: expose `POST /api/query` returning a QueryResult.

**Done when:** a valid request returns a QueryResult; an unknown metric/dimension/operator is rejected before any SQL runs.

### Stream C — Frontend Shell + Dashboard (~3h15m, longest stream)

*Builds entirely against Wave 0 fixtures. Never blocked by backend progress.*

- [x] **C.1** (20 min) App shell, routing, layout, chart library wired up.
- [x] **C.2** (20 min) API client module — the single place that calls the backend. Points at fixtures now, flip one flag in Wave 2.
- [x] **C.3** (30 min) Six KPI cards. The Average Delivery Time card shows its basis inline (e.g. "3.83 days · n=370, incl. exception") since its denominator deliberately differs from Delivered Orders (359) — PRD §8. *(FR-01–FR-04)*
- [x] **C.4** (30 min) Chart 1 — order volume over time (weekly).
- [x] **C.5** (30 min) Chart 2 — on-time vs. delayed by carrier.
- [x] **C.6** (20 min) Filter bar: date presets/custom dates, carrier, and region. Filters re-call the same query endpoint. *(NFR-01)*
- [x] **C.7** (20 min) Data table for the active selection, plus the **empty-result state** — a valid query returning 0 rows (easy to hit once the date filter narrows) must render "no orders match these filters" with the active filters echoed, never a blank panel or a zeroed-out chart that reads as real data. Same state is reused on the Ask Operations page. *(NFR-04 — this was the one failure state with no owner; invalid CSV is B1.2, unsupported query is E.3, forecast insufficiency is D.5.)*
- [x] **C.8** (25 min) Ask Operations page: input box, answer display, chart slot, table slot, explainability panel (collapsible). Renders from the AskResponse fixture. The panel must handle both shapes — query answers (metric, plan, filters, `metric_basis`) and forecast answers (horizon, method, history window, baseline vs. forecast level, recommendation rule), including the `time_range.means` label so a history window is never displayed as if it were a reported period.

**Done when:** the whole UI is navigable and correct against fixtures, with zero backend running.

### Stream D — Forecast Tool (~1.5h)

*Needs only raw order dates — independent of the metric layer.*

- [x] **D.1** (15 min) `backend/tools/forecast.py`: build the weekly demand series from `order_date` (**51 complete weeks**, 2–28 orders/week — the data starts Wed and ends Tue, so the first and last ISO weeks are part-weeks and are excluded).
- [x] **D.2** (30 min) One basic method — least-squares trend fitted over the trailing 12 weeks, honoring `horizon_weeks` (1–8) from the request. Do not implement two to compare. Twelve weeks, not four: weekly counts scatter by ~4 orders around a mean of 7.5, so a slope through four points is noise.
- [x] **D.3** (15 min) Recommendation with **fixed rule values, not placeholders** *(FR-14, PRD §12)*:
  - `B` = mean weekly orders over the **trailing 4 complete weeks** before the forecast start.
  - `F` = mean of the forecast values across the horizon. The projection must therefore be fitted over a **wider** window than `B`: a flat 4-week mean would make `F` equal `B` for every dataset and neither threshold could ever be crossed.
  - `F > B × 1.10` → `increase_capacity`, delta = `ceil(F − B)` orders/week.
  - `F < B × 0.90` → `no_increase` (softening demand).
  - otherwise → `hold`.
  - Return `B`, `F`, the delta, the action, and the rule string — the text is assembled here, never by the LLM.
- [x] **D.4** (10 min) Methodology note + `history_window` (start, end, observation count). *(FR-13)*
- [x] **D.5** (10 min) Insufficient-history guard: **fewer than 8 complete weeks** → `insufficient_data: true` + reason, no number. The supplied dataset has 51 complete weeks so this never fires in practice — test it with a deliberately truncated fixture.
- [x] **D.6** (10 min) `backend/api/forecast.py`: expose `POST /api/forecast` returning a ForecastResult.

**Done when:** a 4-week forecast returns values, horizon, method name, methodology note, history window, and a recommendation carrying B/F/delta — all computed in code, none from an LLM; an 6-week-history fixture returns `insufficient_data: true`.

### Stream E — AI Orchestrator (~2h20m — E.1 40m, E.2 25m, E.3 20m, E.4 20m, E.5 20m, E.6 5m, E.7 10m)

*Builds against the StructuredRequest contract + a stubbed Query Tool returning fixture data. Swaps in the real tool in Wave 2.*

- [x] **E.1** (40 min) `backend/agents/orchestrator.py`: LLM tool-calling setup with schema-constrained output producing a valid StructuredRequest. Never raw SQL. *(PRD §9.2)*
- [x] **E.2** (25 min) Routing via the `operation` discriminator: `query` → Query Tool, `forecast` → Forecast Tool. Extracting `horizon_weeks` from phrasing like "the next 4 weeks" is part of this task — verify it against "forecast demand for the next 4 weeks" (→ 4) and a bare "forecast demand" (→ a documented default, recommend 4). If using provider function-calling, exposing two tools makes the model's tool choice *be* the routing.
- [x] **E.3** (20 min) Unsupported path: outside the approved grammar → explanation + list of supported capabilities, `unsupported: true`. *(FR-15)*
- [x] **E.4** (20 min) Answer composition: one grounded sentence built only from returned values — no model-invented numbers. *(FR-07)*
- [x] **E.5** (20 min) Explainability assembly: fill contract 4 from the validated request + metric registry's `definition_text` + `metric_basis` (row count + inclusion rule) + result. For forecasts also populate `forecast_details` (horizon, method, history window, baseline, forecast level, recommendation rule) and label `time_range.means` as `history_window` rather than `reported_period`. *(FR-09, FR-10, PRD §11)*
- [x] **E.6** (5 min) `backend/api/ask.py`: expose `POST /api/ask` returning an AskResponse.
- [x] **E.7** (10 min) `backend/core/chart_rules.py` — **owns FR-08**, which no other task covers. Three hardcoded rules, an if/elif/else, not a rules engine:

  1. result has a time series → `line` (forecast included; projected segment styled differently)
  2. result has a category dimension → `bar`
  3. otherwise → `table` (a single scalar renders as a KPI number)

  Called when assembling `AskResponse`, so `chart.type` is decided once in application code. The model never picks it — NFR-03 — and `visualization: "auto"` means "apply these three rules," not "let the model decide." The dashboard's two fixed charts (C.4/C.5) don't consult this at all; it exists only for Ask Operations, where the result shape isn't known ahead of time. Stream C renders whatever `type` says.

**Done when:** the three spec example questions produce correct StructuredRequests against stubs, an out-of-scope question returns `unsupported: true`, and a ranking result yields `bar` / a weekly trend yields `line` / a single KPI yields `null` without any model involvement. *(FR-08)*

### Stream G — Langfuse Traceability (~1h15m)

*Adds operational tracing for the AI request lifecycle without making Langfuse a runtime dependency for answering questions.*

- [x] **G.1** (10 min) Add the Langfuse SDK and document the required environment variables: `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL`, plus an enable/disable flag if needed. Use deployment secret management or a local untracked `.env`; never commit secret values.
- [x] **G.2** (20 min) Create `backend/observe/langfuse.py` as a no-op-safe adapter that starts and flushes a root trace per Ask Operations request, with configurable host and enabled state. It must fail open: tracing errors must not fail or materially delay the user response.
- [x] **G.3** (25 min) Instrument the end-to-end agent lifecycle: root trace for the question/request, generation spans for model calls, spans for query/forecast/decline tool calls, and captured duration, status, errors, selected model, `thread_id`, and deployment environment. Redact API keys and unnecessary personal/sensitive data.
- [x] **G.4** (10 min) Correlate the Langfuse trace ID with application request/answer logs and, if the response contract is extended, expose only the non-secret trace ID for support/debugging. Keep the existing explainability payload as the user-facing “how this answer was produced” view.
- [x] **G.5** (10 min) Add tests for enabled and disabled tracing, flush/error fallback, redaction, and one trace containing model plus tool observations. Document local setup and production secret configuration in `README.md`.

**Done when:** every `/api/ask` analytics request creates a searchable Langfuse trace containing the model and governed tool steps, trace failures leave the API response unaffected, and no credential or unredacted sensitive value is sent to Langfuse.

### Stream F — Deployment Scaffolding (~45 min)

*Deploy something trivial early — deployment surprises are the classic end-of-project time sink.*

- [ ] **F.1** (20 min) Host setup (Vercel/Railway/Render/Fly), env var plumbing, deploy the Wave 0 skeleton as a smoke test.
- [ ] **F.2** (10 min) Confirm `.gitignore` covers `.env`; no secrets in the repo.
- [x] **F.3** (15 min) `README.md` with setup + env vars, system overview + design decisions + data flow, question interpretation & tool selection, assumptions/limitations, future improvements, and AI-usage disclosure.

**Done when:** an empty-but-real app is live at a public URL and redeploys on push.

---

## WAVE 2 — Integration (~1h, needs streams merged)

*Do these in order; each is a stub deletion.*

- [x] **I.1** (10 min) B2 → B1: point the Query Tool at the real metric registry, delete the stub registry. Re-verify ground-truth values through `POST /api/query`.
- [x] **I.2** (15 min) E → B2 + D: point the orchestrator at the real Query Tool and real Forecast Tool, delete fixtures. Re-run the three spec example questions end to end.
- [x] **I.3** (15 min) C → backend: flip the API client off fixtures. Verify dashboard numbers match the ground truth and that Ask Operations renders real answers, charts, and explainability.
- [x] **I.4** (10 min) A → everything: enable the auth guard on all routers; confirm the frontend still works through the gate.
- [x] **I.5** (10 min) Reconciliation check: the same metric+filter through the dashboard and through Ask Operations returns identical numbers. *(NFR-01 — this is the single most likely place to lose Data Correctness points.)*
- [x] **I.6** (15 min) G → E: wire the observability adapter into the live agent/orchestrator boundaries, verify model/tool spans for a real Ask Operations request, and confirm tracing remains non-blocking when Langfuse is unavailable.

---

## WAVE 3 — Finalize (~45 min)

- [ ] **Z.1** (15 min) Deploy the integrated app; verify the public URL end to end with the auth credential.
- [x] **Z.2** (25 min) Finish `README.md`: document environment variables, design decisions/data flow, the `exception` denominator tradeoff (`n=370` vs `n=359`), the single forecasting method and thresholds, minimal Basic Auth, and server-side Ask Operations threads with stateless history fallback.
- [x] **Z.3** (5 min) AI-usage disclosure section, per the spec's note.

---

## PRD coverage map

Which stream discharges which part of the PRD. Anything not listed here is not being built.

| Stream | PRD sections | Requirements |
|---|---|---|
| A — Auth | §5.0 Access | FR-16 |
| B1 — Ingestion + Metrics | §7 Data Requirements, §8 Metric Definitions | FR-01–FR-04 (computation), FR-11, NFR-02 |
| B2 — Query Tool | §9.2 validation, Appendix A grammar | FR-12, NFR-03 |
| C — Frontend/Dashboard | §5.1 Interface A, §5.2 Interface B (UI), §10 (rendering) | FR-01–FR-05, FR-10 (display), NFR-04 (empty result) |
| D — Forecast Tool | §12 Forecasting | FR-13, FR-14, NFR-04 (insufficient history) |
| E — Orchestrator | §9, §9.1, §9.2, §10 (selection rules), §11 Explainability | FR-06, FR-07, FR-08, FR-09, FR-15, NFR-04 (unsupported) |
| F — Deploy | §15 Deliverables | NFR-05, NFR-06 |
| G — Langfuse Traceability | Operational observability for §9 AI orchestration and Ask Operations | Trace per request, model/tool spans, correlation ID, redaction, fail-open behavior |
| Wave 2 (integration) | §14 NFR-01 | NFR-01 — reconciliation is only testable once C and B2 are wired together, so it belongs to task I.5, not to any single stream |

Two requirements are easy to lose because they sit between streams — both are now assigned explicitly:

- **FR-08 (automatic chart-type selection)** lives in **E.7**, not in Stream C. C.4/C.5 are two *fixed* dashboard charts (FR-05); FR-08 is the deterministic result-shape → chart-type rule from §10, applied in backend code so `chart.type` is decided once and never by the model (NFR-03).
- **NFR-04 (failure handling)** is split by failure kind: invalid CSV → B1.2, unsupported question → E.3, insufficient forecast history → D.5, empty result set → C.7.

## File-ownership map (conflict avoidance)

| Owner | Files |
|---|---|
| Wave 0 (then frozen) | `backend/main.py`, `backend/core/schemas.py`, `backend/core/fixtures.py`, `.env.example` |
| Stream A | `backend/api/auth.py`, `frontend/auth/**` |
| Stream B1 | `backend/core/ingestion.py`, `backend/core/status_rules.py`, `backend/core/metrics.py` |
| Stream B2 | `backend/tools/query.py`, `backend/api/query.py` |
| Stream C | `frontend/**` (except `frontend/auth/**`) |
| Stream D | `backend/tools/forecast.py`, `backend/api/forecast.py` |
| Stream E | `backend/agents/orchestrator.py`, `backend/api/ask.py`, `backend/core/chart_rules.py` |
| Stream F | deploy config, `.gitignore`, `README.md` |
| Stream G | `backend/observe/langfuse.py`, `backend/tests/test_observability.py`, Langfuse dependency/config; Stream G integration edits land in I.6 |

If a stream believes it needs to edit a file it doesn't own, that's a signal the Wave 0 contract was wrong — fix the contract deliberately and tell the other streams, rather than editing across the boundary.

## If running this with parallel agents

Give each agent: the PRD, this document, its stream's tasks only, and its file-ownership row. Tell it explicitly not to touch files outside that row and to code against `schemas.py` + `fixtures.py`. The critical-path pairing is B1 → B2; if you only have two workers, run B1+B2 on one and C on the other, then fold in D/E.

## If working solo

Ignore the wave structure and run: Wave 0 → A → B1 → B2 → C → D → E → Wave 2 → Wave 3. That's the earlier sequential plan, and the contracts from Wave 0 still pay for themselves.

## If short on time

Cut in this order: extra filters and extra breakdowns first; then Stream D down to the simplest method with no chart polish; then trim the explainability panel to a plain payload dump (present but unpolished). Never cut Wave 0, B1, B2, C.3–C.5, **E.7**, I.5, or Wave 3 — those carry most of the graded weight and the explicit deliverables. E.7 is only 15 minutes but it is the whole of FR-08 ("the system must automatically select an appropriate chart type"), so cutting it drops a named spec requirement rather than just polish.
