# AI Logistics Analytics Dashboard

AI-powered logistics analytics dashboard with forecasting and Q&A capabilities.

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, pandas, Uvicorn
- **AI orchestration:** deepagents/LangChain with an OpenAI-compatible model
- **Frontend:** Next.js 15, React 19, TypeScript, Recharts
- **Package Manager:** uv (Python), npm (Node.js)

## Prerequisites

- Python 3.11+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

## Setup

### 1. Clone & Environment

Obtain the environment values through the separate secure handoff, then create
the local files from the committed templates:

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env.local
```

Replace the placeholders with the separately supplied values. Never commit,
paste into documentation, or share the completed environment files. Both are
covered by the repository's `.gitignore` rules.

### 2. Backend

In the first terminal, from the repository root:

```bash
# Install dependencies
uv sync

# Run development server (http://localhost:8080)
uv run uvicorn backend.main:app --reload --port 8080
```

### 3. Frontend

In a second terminal:

```bash
cd frontend

# Install dependencies
npm install

# Run development server (http://localhost:3001 — the port is set in package.json)
npm run dev
```

As a shortcut, `make dev` installs dependencies and starts both services from
the repository root. Use `NEXT_PUBLIC_DATA_MODE=fixtures` if you only want to
work on the frontend with bundled sample data; this mode does not need the
backend or an LLM key.

### 4. Access

- Frontend: http://localhost:3001
- Backend API docs: http://localhost:8080/docs
- Health check: http://localhost:8080/health

The two ports are not interchangeable: the backend's CORS allow-list
(`FRONTEND_ORIGIN`) defaults to `http://localhost:3001`, and the frontend calls
the backend at `NEXT_PUBLIC_API_BASE_URL`, which defaults to
`http://localhost:8080`. Change one and you must change the other.

## API Authentication

The API uses HTTP Basic Auth. Configure its credentials only in the local
`.env` file or the deployment platform's secret store using the values supplied
separately. Do not commit or include credential values in documentation.

## Environment Variables

The tables below document only the required variable names and their purpose.
Values are intentionally omitted and distributed separately.

Backend (`.env`):

| Variable | Sensitive | Description |
|----------|-----------|-------------|
| `APP_USERNAME` | Yes | HTTP Basic Auth username. The API fails closed if either credential is unset. |
| `APP_PASSWORD` | Yes | HTTP Basic Auth password. |
| `LLM_API_KEY` | Yes | Provider credential required for analytical `/api/ask` questions. Dashboard queries, health, greetings, and local carrier definitions do not need it. |
| `LLM_BASE_URL` | No | OpenAI-compatible API root. |
| `LLM_MODEL` | No | Model identifier understood by the configured provider. |
| `ASK_NARRATION` | No | `composed` makes the server write answer prose; `verified` permits model prose only when every number is grounded in tool output. Invalid values fall back to `composed`. |
| `DATA_CSV_PATH` | No | Logistics CSV path, resolved from the backend process working directory. |
| `FRONTEND_ORIGIN` | No | The one browser origin allowed by CORS. |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse project public key. Tracing is skipped, with no error, when this or the secret key is unset — see [Observability](#observability-langfuse-tracing). |
| `LANGFUSE_SECRET_KEY` | Yes | Langfuse project secret key. |
| `LANGFUSE_BASE_URL` | No | Self-hosted or region-specific Langfuse host. Omit for Langfuse's default cloud host. |
| `LANGFUSE_ENABLED` | No | Explicit override: `true` forces tracing on, `false` forces it off regardless of the keys above. |
| `LANGFUSE_TRACING_ENVIRONMENT` | No | Environment label attached to every trace (e.g. `development`, `staging`, `production`). Defaults to `development`. |
| `CUSTOM_TAGS` | No | JSON object of extra labels attached to every trace as tags and metadata, e.g. `{"org":"spaceship","project":"dashboard-logistic","developer":"hasnan"}`. Malformed JSON is ignored, not fatal. |

The provider is any OpenAI-compatible chat-completions endpoint. `LLM_MODEL`
must match what that endpoint expects — OpenRouter ids carry a provider prefix
(`openai/gpt-5.6-luna`), `api.openai.com` ids do not.

Frontend (`frontend/.env.local`):

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_BASE_URL` | Backend base URL. |
| `NEXT_PUBLIC_API_USERNAME` | Basic auth username; must match `APP_USERNAME`. |
| `NEXT_PUBLIC_API_PASSWORD` | Basic auth password; must match `APP_PASSWORD`. |
| `NEXT_PUBLIC_DATA_MODE` | `api` uses the backend; `fixtures` renders bundled sample responses without it. |

All `NEXT_PUBLIC_*` values are embedded in browser JavaScript and cannot be
treated as secrets. The current Basic Auth pair is therefore reviewer access,
not production-grade authentication. When changing either local port, also
update `NEXT_PUBLIC_API_BASE_URL` or `FRONTEND_ORIGIN` as appropriate.

## System overview

The application has two interfaces over one read-only logistics dataset:

- The **Operations Dashboard** sends predefined structured requests to
  `POST /api/query` for KPIs, weekly volume, and carrier performance.
- **Ask Operations** sends a natural-language question to `POST /api/ask`. An
  LLM interprets the request, but governed Python tools perform every
  calculation. `POST /api/forecast` also exposes the forecast directly to a
  structured client.

The backend loads and validates the CSV once into an in-memory pandas
`DataFrame`. Both the dashboard and agent tools use the same query engine,
metric registry, and status rules.

```text
Dashboard filters ──> POST /api/query ───────────────────────────────┐
                                                                  │
Natural-language question ─> POST /api/ask                         │
  ├─> small-talk templates / carrier glossary (no LLM)             │
  └─> LLM interpretation ─> query_tool or forecast_tool             │
                               │                                   │
                               v                                   v
                    validated structured request ─> query/forecast engine
                                                        │
                                                        v
                  validated CSV ─> status rules ─> metric registry
                                                        │
                                                        v
                         composed answer + table + deterministic chart
                                      + explainability trace
```

## Run the apps

From the repository root, install dependencies and create the local environment
files:

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env.local
uv sync
cd frontend && npm install
```

Start the backend and frontend in separate terminals:

```bash
# Terminal 1, repository root
uv run uvicorn backend.main:app --reload --port 8080

# Terminal 2, repository root
cd frontend && npm run dev
```

Or run both with `make dev`. Then open `http://localhost:3001`. The backend
health check is `http://localhost:8080/health` and interactive API docs are at
`http://localhost:8080/docs`. API requests require the `APP_USERNAME` and
`APP_PASSWORD` values from `.env`.

For frontend-only work, set `NEXT_PUBLIC_DATA_MODE=fixtures` in
`frontend/.env.local`; this uses bundled responses and does not require the
backend or an LLM key.

## Test the app

Run the complete test suite from the repository root:

```bash
uv run pytest -q            # backend tests
cd frontend && npm test     # frontend tests
```

The Makefile combines both commands with `make test`. Useful focused checks:

```bash
uv run pytest backend/tests/test_data_correctness.py -v
uv run pytest backend/tests/test_agent.py -v
cd frontend && npm run lint
```

The backend tests cover ingestion validation, metric correctness, query and
forecast tools, API authentication, agent tool calls, follow-up turns,
grounding, localization, and fail-open Langfuse observability. Frontend tests
cover API/fixture clients, formatting, fixtures, and UI support code.

## Capabilities and limitations

The app can:

- Show logistics KPIs, trends, breakdowns, rankings, filters, and comparisons
  from the validated CSV dataset.
- Forecast weekly order demand for a bounded 1–8 week horizon when enough
  complete weekly history exists.
- Answer natural-language questions in Indonesian, English, or Chinese through
  governed `query_tool`, `forecast_tool`, and `decline_tool` calls.
- Answer carrier glossary questions and greetings locally without an LLM.
- Return tables, deterministic charts, explainability data, and optional
  Langfuse traces for Ask Operations.
- Continue an Ask Operations conversation with client-supplied history or a
  server-held `thread_id`.

The app does not:

- Accept writes, edits, deletes, shipment updates, or database transactions;
  the CSV is loaded read-only into memory.
- Track live shipment locations, connect to carrier APIs, or provide real-time
  operational status.
- Include shipping cost, revenue, customer, warehouse, inventory, route,
  driver, or other fields absent from the CSV.
- Support arbitrary SQL, arbitrary dimensions/metrics, unbounded forecasts, or
  unsupported analytical questions; these are rejected or returned as a
  grounded unsupported response.
- Guarantee a forecast when the dataset has insufficient complete history.
- Work on analytical Ask Operations questions without `LLM_API_KEY`; direct
  dashboard queries, health checks, greetings, and local carrier glossary
  questions still work without it.

### Key design decisions

- **One metric implementation.** `backend/core/metrics.py` is the only KPI
  registry, and `backend/core/status_rules.py` is the only definition of status
  membership. The dashboard and conversational paths cannot drift into
  different formulas.
- **Structured requests, never generated SQL.** Pydantic allow-lists metrics,
  dimensions, filters, operators, sorting, row limits, and forecast horizons
  before pandas runs. Semantic checks reject combinations that parse but do
  not make sense.
- **The model is an orchestrator, not a calculator.** It never receives CSV
  rows or computed values. Tools store complete result blocks for the API and
  return only receipts such as `Stored result 1: delay_rate by carrier` to the
  model.
- **Grounded output.** In the default `composed` mode, application code writes
  all numerical prose from computed results. In `verified` mode, model-written
  prose is used only after every number is matched to tool output; otherwise
  the composed answer wins.
- **Deterministic presentation.** A time breakdown becomes a line chart, one
  categorical breakdown becomes a bar chart, and scalar or multi-dimensional
  output remains a table. The model does not select chart types, and chart data
  is built from the same rows shown in the table.
- **Read-only, fail-closed data handling.** There is no mutation endpoint or
  database write path. Ingestion rejects missing columns, malformed dates,
  reversed delivery dates, duplicate order IDs, and unknown statuses.
- **Visible reasoning boundary.** Each result includes the structured request,
  metric definition and population, resolved dates and filters, query plan,
  result preview, and model-versus-compute timing.

### Main backend modules

| Module | Responsibility |
|--------|----------------|
| `backend/core/ingestion.py` | Load, validate, and cache the CSV. |
| `backend/core/status_rules.py` | Define delivered, delayed, and delivery-dated populations. |
| `backend/core/metrics.py` | Compute the approved KPI registry. |
| `backend/tools/query.py` | Resolve dates, apply filters/grouping/sorting, and execute queries. |
| `backend/tools/forecast.py` | Produce weekly demand forecasts and capacity guidance. |
| `backend/agents/agent.py` | Configure the agent prompt, planning loop, limits, threads, and subagents. |
| `backend/tools/agent.py` | Validate tool arguments and collect governed result blocks. |
| `backend/core/answers.py` / `backend/core/grounding.py` | Compose answers and verify optional model narration. |
| `backend/agents/orchestrator.py` | Run one question and assemble the API response. |
| `backend/observe/langfuse.py` | Langfuse tracing adapter for Ask Operations, fail-open by construction. |

The backend package is organized by responsibility: `api/` contains FastAPI
routers, `agents/` contains LLM orchestration, `tools/` contains governed
analytics tools, `observe/` contains optional tracing, and `core/` contains
shared contracts and domain logic. `backend/main.py` is the application
composition root.

## Observability (Langfuse tracing)

Every `POST /api/ask` run that reaches the agent (i.e. not a small-talk or
carrier-glossary shortcut) can be wrapped in a Langfuse trace: one root span
per request, a generation span per model call, and a span per `query_tool` /
`forecast_tool` / `decline_tool` call — all nested automatically because the
LangChain callback handler is attached to the agent's `invoke` config. The
trace is tagged with the conversation's `thread_id` (as the Langfuse session)
and a deployment-environment label, so a support conversation can be
correlated end to end.

**This is entirely optional and fails open.** If `LANGFUSE_PUBLIC_KEY` or
`LANGFUSE_SECRET_KEY` is unset, tracing is skipped with no log line and no
network call — the default state for a fresh checkout. If Langfuse is
misconfigured or unreachable, the adapter catches the failure, logs a warning,
and the request completes normally; a broken exporter has been verified to
neither raise nor add meaningful latency to the response (the SDK batches and
exports off the request path). Nothing about the answer, the dashboard, or the
existing `explainability` payload — the user-facing "how this was produced"
view — changes based on whether tracing is on.

**Local setup:**

1. Create a free project at Langfuse (self-hosted or cloud) and copy its
   public/secret key pair.
2. Add to `.env`:
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_BASE_URL=   # leave blank for Langfuse Cloud, or set your self-hosted URL
   ```
3. Ask a question through `/api/ask` and check the Langfuse project's Traces
   view for `ask-operations-request`.

Each `query_tool` observation records the structured request as its input and
the computed `QueryResult` (columns, rows, population, and truncation state) as
its output. This lets reviewers compare the agent's requested query with the
ground truth used to build the dashboard answer. Raw filtered shipment rows are
not exported by default; set `LANGFUSE_INCLUDE_QUERY_SOURCE_ROWS=true` only
when that data is safe to send to Langfuse.

Optionally set `CUSTOM_TAGS` to a JSON object to stamp every trace with extra
labels (team, project, owner, ...), e.g.:
```
CUSTOM_TAGS={"org":"spaceship","project":"dashboard-logistic","developer":"hasnan"}
```
Each key becomes both a `key:value` tag (filterable in the Traces list) and a
metadata field on the trace.

**Production:** set the same three variables through the deployment
platform's secret store, never in a committed file — `.env.example` documents
the variable names only, with empty values. Set `LANGFUSE_TRACING_ENVIRONMENT`
per deployment (`staging`, `production`, ...) so traces from different
environments don't mix in one project view. `LANGFUSE_ENABLED=false` is the
kill switch if tracing ever needs to be disabled without removing the keys.

Correlation: when tracing is active, the backend logs
`ask_operations thread=<thread_id> langfuse_trace=<trace_id>` at INFO level, so
an application log line can be matched to its Langfuse trace for debugging. No
API key, password, or other credential is ever sent to Langfuse — outgoing
metadata is passed through `backend.observe.langfuse.redact`, which masks any
key whose name looks credential-shaped.

## How questions are interpreted and tools are selected

`POST /api/ask` uses the following routing process:

1. Whole-message greetings and thanks are answered from local English,
   Indonesian, or Chinese templates. Informational questions about a supported
   carrier are answered from a source-backed local glossary. Neither path calls
   the model.
2. For an analytical question, the temperature-zero LLM resolves conversational
   context and translates the wording into an allow-listed metric, dimensions,
   filters, time range, sort, limit, or forecast horizon.
3. The model selects `query_tool` for historical counts, rates, delivery time,
   trends, comparisons, and rankings; `forecast_tool` for future weekly order
   demand; or `decline_tool` when the requested information is absent.
4. Compound questions produce one tool call per distinct figure or comparison
   window. Open-ended requests such as “where are delays concentrated?” may be
   delegated to a restricted trend investigator that runs several governed
   breakdowns.
5. Tool arguments are validated. A rejected call is returned to the agent so
   it can correct the arguments within the run limits (8 model calls and 12
   tool calls). If no valid computation is possible, the API returns HTTP 200
   with `unsupported: true` and an explanation instead of guessing.
6. The tool computes and stores the result while exposing only a receipt to the
   model. Application code then creates the answer, table, chart, and trace.

Follow-ups can send the returned `thread_id`; otherwise clients may replay up
to 10 question/answer turns in `history`. A thread takes precedence over
history. The process retains at most 200 recent threads in memory.

### Supported analytical grammar

| Part | Supported values |
|------|------------------|
| Metrics | `total_orders`, `delivered_orders`, `delayed_orders`, `on_time_rate`, `delay_rate`, `avg_delivery_time`, `order_demand` |
| Breakdowns | `order_date`, ISO `week`, `month`, `carrier`, `origin_city`, `destination_city`, `status`, `region`, `product_category` |
| Filters | `order_date`, `delivery_date`, `carrier`, `origin_city`, `destination_city`, `status`, `region`, `product_category` |
| Operators | `eq`, `neq`, `in`, `not_in`; `gt`, `gte`, `lt`, and `lte` only for date fields |
| Time ranges | Inclusive explicit dates, `previous_week`, `previous_month`, `last_N_weeks`, `last_N_months` |
| Ranking | Sort ascending or descending by the requested metric or a selected dimension; return 1–1000 rows |
| Forecasting | Aggregate `order_demand`, weekly grain only, 1–8 weeks ahead, optionally filtered |

Status-derived metrics (`delivered_orders`, `delayed_orders`, `on_time_rate`,
and `delay_rate`) cannot be broken down by `status`, because each status group
would make those values degenerate. `avg_delivery_time`, `total_orders`, and
`order_demand` can use every listed dimension.

Forecasts use counts from complete ISO weeks, require at least eight complete
weeks, and fit a least-squares line over up to the latest 12 complete weeks.
The mean projected demand is compared with the trailing four-week mean: above
10% recommends increased capacity, below -10% recommends no increase, and the
middle band recommends holding. Negative projections are floored at zero.

## Assumptions, simplifications, and limitations

- The bundled dataset is a 400-row synthetic snapshot covering 2025. It is
  treated as the source of truth; the application validates internal
  consistency but cannot establish real-world accuracy.
- Relative dates are anchored to the dataset's latest `order_date`, not the
  wall clock. This keeps “last month” meaningful for a historical snapshot,
  and the resolved dates are returned in explainability metadata.
- `delivered` means on time and `delayed` means delivered late. Both count as
  delivered for rate denominators. `exception` is excluded from on-time/delay
  rates but included in average delivery time when it has a delivery date.
- `order_demand` means number of order rows, not item quantity, SKU demand,
  inventory consumption, weight, revenue, or shipment capacity units.
- The CSV is loaded once per backend process. File changes require a restart;
  there is no live ingestion, database, incremental refresh, or multi-dataset
  join.
- The forecast is a deliberately simple univariate trend. It has no seasonality,
  holidays, promotions, confidence intervals, backtesting/model selection, or
  causal features, and it forecasts a filtered aggregate rather than separate
  grouped series.
- “Where are delays concentrated?” can be answered with breakdowns, but “why
  did delays happen?” cannot: correlation and segment differences are not
  evidence of cause.
- Conversation state and the LRU list of 200 threads are process-local. A
  restart or another replica loses that state; replayed `history` is the
  fallback and only the latest 10 turns are accepted.
- HTTP Basic Auth is sufficient for a reviewer MVP but has no accounts, roles,
  expiry, or server-side browser session. Use TLS outside localhost. Public
  frontend environment variables must not hold privileged production secrets.
- If the Ask page cannot reach the model/API, it displays a clearly labelled
  bundled sample response. That fallback is a UI demonstration, not a live
  answer to the submitted question.

### Unsupported queries

The system intentionally declines requests for data or operations outside the
grammar, including:

- cost, profit, revenue, customer satisfaction, SLAs, inventory levels, or
  other fields that are not governed by the application;
- SKU-level, quantity-based, monthly, or longer-than-eight-week forecasts;
- route inference, live tracking, geospatial analysis, optimization, anomaly
  attribution, or causal explanations;
- arbitrary calculations, arbitrary SQL, free-form joins, writes, updates, or
  deletion; and
- unknown metrics/dimensions/operators, lexicographic range comparisons on
  label fields, or semantically invalid metric/dimension combinations.

## Future improvements

- Replace the static CSV/cache with authenticated warehouse or operational
  database access, scheduled ingestion, freshness metadata, and data-quality
  monitoring.
- Add real identity, role-based authorization, server-managed sessions, secret
  handling, audit logs, rate limits, and durable/shared conversation storage.
- Expand the governed semantic layer with quantity, SKU, cost, SLA, inventory,
  and route metrics while preserving explicit definitions and reconciliation
  tests.
- Add grouped and longer-horizon forecasting, seasonality and external
  regressors, confidence intervals, backtesting, model selection, and forecast
  accuracy monitoring before using recommendations operationally.
- Improve interpretation with ambiguity detection and clarification, entity
  normalization, multilingual analytical prompts, and evaluation sets for tool
  selection and multi-turn questions.
- Move compound-result synthesis into a deterministic cross-result composer so
  comparisons remain concise without relying on optional model narration.
- Add pagination/export, richer multi-dimensional visualizations, accessibility
  testing, observability, caching, and end-to-end browser tests.

## How the numbers are verified

Both the dashboard (`POST /api/query`) and the agent compute through one
registry, `backend/core/metrics.py`, over the status semantics in
`backend/core/status_rules.py`. So NFR-01 — the two paths must agree — holds by
construction rather than by discipline: there is no second implementation that
could drift. The frontend only formats (`KpiCard.tsx`), and every chart is
built from the rows of the table beside it, so neither can show a different
number.

On top of that, `backend/tests/test_data_correctness.py` checks each KPI three
ways, and the three have to meet:

1. an **oracle** that recomputes every KPI from the CSV with the standard
   library only — no pandas, no application code — transcribed from the
   definitions in PRD 8 rather than from `metrics.py`;
2. the **registry** the application computes through;
3. the **pinned values** in `test_metrics.py` and in `frontend/lib/fixtures.ts`
   (that second copy is what fixtures mode renders, so it is asserted against
   the backend rather than trusted).

Point 1 is the one the golden values cannot make. A hard-coded expectation was
read off the implementation it now guards, so a definition that was wrong from
the start agrees with itself for ever; an independent transcription of the spec
disagrees.

The same module sweeps dashboard-versus-agent equality across every metric and
every dimension either will accept, plus filters, presets and ranking — 66
combinations rather than three hand-picked ones. Ingestion fails closed on a
missing file, missing columns, non-ISO dates, a delivery date that precedes its
order date, duplicate `order_id`s, and unmapped status values.

## Testing

```bash
# Run backend and frontend tests
uv run pytest
cd frontend && npm test

# Or run both test suites through Make
make test

# Run frontend tests in watch mode
cd frontend && npm run test:watch

# Run with coverage
uv run pytest --cov=backend
```

Pull requests, and pushes to `main`, also run both suites through GitHub Actions
in `.github/workflows/ci.yml`. The backend job is advisory rather than a merge
gate: provisioning its environment (deepagents pulls in langchain, anthropic and
google-genai, so the virtualenv is ~209 MB) costs minutes on a runner, while the
283 backend tests themselves finish in about five seconds. Run `make test`
before pushing and treat the Actions result as a second opinion, not the check
you wait on.

## Docker

```bash
# Build and run both services (backend :8080, frontend :3001)
docker compose up --build

# Or build the backend image on its own
docker build -t logistics-backend .
docker run -p 8080:8080 --env-file .env logistics-backend
```

## Deployment (Railway)

Both services deploy from this one repo as two services inside one Railway
project ("environment"), each built from its own `Dockerfile` via the
matching `railway.json` (`/railway.json` for the backend, `frontend/railway.json`
for the frontend). Railway assigns each service its own `PORT` at runtime;
both Dockerfiles already read it dynamically instead of hardcoding one.

1. **Create the project.** [railway.com](https://railway.com) → New Project →
   Deploy from GitHub repo → select this repo.
2. **Backend service.** Add a service from the same repo, Root Directory `/`.
   Railway detects `railway.json` and builds `Dockerfile` automatically. Set
   these Variables on the service (Settings → Variables):
   - `APP_USERNAME`, `APP_PASSWORD` — reviewer credentials
   - `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` — see the table above
   - `FRONTEND_ORIGIN` — filled in after step 4 below
   Then Settings → Networking → **Generate Domain** to get a public URL
   (`https://<backend>.up.railway.app`).
3. **Frontend service.** Add a second service from the same repo, Root
   Directory `/frontend`. It picks up `frontend/railway.json` and builds
   `frontend/Dockerfile`. Set these build-time Variables (the Dockerfile
   declares them as `ARG`s, so Railway bakes them into the client bundle):
   - `NEXT_PUBLIC_API_BASE_URL` — the backend's public URL from step 2
   - `NEXT_PUBLIC_API_USERNAME`, `NEXT_PUBLIC_API_PASSWORD` — match step 2
   - `NEXT_PUBLIC_DATA_MODE=api`
   Then Settings → Networking → Generate Domain for the frontend too.
4. **Close the loop.** Go back to the backend service and set
   `FRONTEND_ORIGIN` to the frontend's public URL from step 3, then redeploy
   the backend so CORS allows it. (This order — backend domain, then
   frontend, then back to backend — exists because each origin needs the
   other's URL, which doesn't exist until it deploys once.)

Both services redeploy automatically on every push to `main`. Railway does
not read `docker-compose.yml`; it's kept for local multi-service runs (`docker
compose up`) only, and stays in sync with `Dockerfile` by using the same
default `PORT=8080` when nothing overrides it.

## Makefile Commands

```bash
make setup        # Install all dependencies
make dev          # Run both backend and frontend
make backend      # Run backend only
make frontend     # Run frontend only
make test         # Run tests
make lint         # Run linters
make docker-build # Build Docker image
make docker-run   # Run Docker container
make clean        # Clean build artifacts
```

Assisted by Claude Opus and Sonnet
