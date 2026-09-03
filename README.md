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
