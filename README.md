# AI Logistics Analytics Dashboard

AI-powered logistics analytics dashboard with forecasting and Q&A capabilities.

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn
- **Frontend:** Next.js 15, React 19, TypeScript
- **Package Manager:** uv (Python), npm (Node.js)

## Prerequisites

- Python 3.11+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

## Setup

### 1. Clone & Environment

```bash
cp .env.example .env
# Edit .env with your values (LLM_API_KEY is required for AI features)

cp frontend/.env.example frontend/.env.local
# Keep NEXT_PUBLIC_API_USERNAME/PASSWORD in sync with APP_USERNAME/APP_PASSWORD
```

### 2. Backend

```bash
# Install dependencies
uv sync

# Run development server (http://localhost:8080)
uv run uvicorn backend.main:app --reload --port 8080
```

### 3. Frontend

```bash
cd frontend

# Install dependencies
npm install

# Run development server (http://localhost:3001 — the port is set in package.json)
npm run dev
```

### 4. Access

- Frontend: http://localhost:3001
- Backend API docs: http://localhost:8080/docs
- Health check: http://localhost:8080/health

The two ports are not interchangeable: the backend's CORS allow-list
(`FRONTEND_ORIGIN`) defaults to `http://localhost:3001`, and the frontend calls
the backend at `NEXT_PUBLIC_API_BASE_URL`, which defaults to
`http://localhost:8080`. Change one and you must change the other.

## API Authentication

The API uses HTTP Basic Auth. Configure credentials in `.env`:

```
APP_USERNAME=reviewer
APP_PASSWORD=change-me
```

## Environment Variables

Backend (`.env`):

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_USERNAME` | Basic auth username | `reviewer` |
| `APP_PASSWORD` | Basic auth password | `change-me` |
| `LLM_BASE_URL` | LLM API base URL | `https://openrouter.ai/api/v1` |
| `LLM_API_KEY` | LLM API key | (required) |
| `LLM_MODEL` | LLM model identifier | `openai/gpt-5.6-luna` |
| `DATA_CSV_PATH` | Path to logistics CSV data | `mock_logistics_data.csv` |
| `FRONTEND_ORIGIN` | Origin allowed by CORS | `http://localhost:3001` |

The provider is any OpenAI-compatible chat-completions endpoint. `LLM_MODEL`
must match what that endpoint expects — OpenRouter ids carry a provider prefix
(`openai/gpt-5.6-luna`), `api.openai.com` ids do not.

Frontend (`frontend/.env.local`):

| Variable | Description | Default |
|----------|-------------|---------|
| `NEXT_PUBLIC_API_BASE_URL` | Backend base URL | `http://localhost:8080` |
| `NEXT_PUBLIC_API_USERNAME` | Basic auth username, must match `APP_USERNAME` | `reviewer` |
| `NEXT_PUBLIC_API_PASSWORD` | Basic auth password, must match `APP_PASSWORD` | `change-me` |
| `NEXT_PUBLIC_DATA_MODE` | `api` for the real backend, `fixtures` for sample data with no backend | `api` |

## Testing

```bash
# Run backend tests
uv run pytest

# Run with coverage
uv run pytest --cov=backend
```

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
