# Onboarding Documentation

Panduan lengkap untuk memulai development di proyek AI Logistics Analytics Dashboard.

## Daftar Isi

1. [Prerequisites](#prerequisites)
2. [Development Environment Setup](#development-environment-setup)
3. [Tools & Skills Reference](#tools--skills-reference)
4. [Development Workflow](#development-workflow)
5. [Testing Workflow](#testing-workflow)
6. [Deployment Workflow](#deployment-workflow)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend runtime |
| [uv](https://docs.astral.sh/uv/) | Latest | Python package manager |
| npm | 9+ | Node.js package manager |
| Docker | 24+ | Containerization (optional) |
| Git | 2.30+ | Version control |

---

## Development Environment Setup

### Step 1: Clone & Environment Variables

```bash
# Clone repository
git clone <repository-url>
cd Logistic-web-dashboard

# Setup backend environment
cp .env.example .env
# Edit .env dengan values yang sesuai:
# - APP_USERNAME / APP_PASSWORD → credentials untuk API
# - LLM_API_KEY → API key untuk LLM (OpenRouter/OpenAI)

# Setup frontend environment
cp frontend/.env.example frontend/.env.local
# Pastikan NEXT_PUBLIC_API_USERNAME/PASSWORD sinkron dengan APP_USERNAME/PASSWORD
```

### Step 2: Backend Setup

```bash
# Install dependencies (uv akan membuat .venv otomatis)
uv sync

# Verify installation
uv run python -c "import backend; print('Backend OK')"

# Run development server
uv run uvicorn backend.main:app --reload --port 8080
```

Backend akan berjalan di `http://localhost:8080`

### Step 3: Frontend Setup

```bash
# Install dependencies
cd frontend
npm install

# Run development server
npm run dev
```

Frontend akan berjalan di `http://localhost:3001`

### Step 4: Verify Setup

```bash
# Health check
curl http://localhost:8080/health

# API docs
open http://localhost:8080/docs
```

---

## Tools & Skills Reference

### 1. uv (Python Package Manager)

**Purpose:** Dependency management dan virtual environment untuk backend.

| Command | Description |
|---------|-------------|
| `uv sync` | Install semua dependencies dari pyproject.toml |
| `uv add <package>` | Tambah dependency baru |
| `uv add --dev <package>` | Tambah dev dependency |
| `uv run <command>` | Jalankan command dalam virtual environment |
| `uv run pytest` | Run tests |
| `uv run uvicorn backend.main:app` | Run backend server from the repository root |

**Key Files:**
- `pyproject.toml` — Dependency definitions
- `uv.lock` — Lock file (commit ke repo)
- `.venv/` — Virtual environment (gitignored)

### 2. npm (Node.js Package Manager)

**Purpose:** Dependency management dan script runner untuk frontend.

| Command | Description |
|---------|-------------|
| `npm install` | Install semua dependencies |
| `npm run dev` | Run development server (port 3001) |
| `npm run build` | Build production bundle |
| `npm run start` | Run production server |
| `npm run lint` | Run ESLint |

**Key Files:**
- `frontend/package.json` — Dependencies & scripts
- `frontend/package-lock.json` — Lock file
- `frontend/node_modules/` — Dependencies (gitignored)

### 3. Makefile

**Purpose:** Shortcut untuk common development tasks.

```bash
make setup        # Install semua dependencies (uv sync + npm install)
make dev          # Run backend + frontend secara parallel
make backend      # Run backend only
make frontend     # Run frontend only
make test         # Run backend tests
make test-cov     # Run tests dengan coverage report
make lint         # Run frontend linter
make docker-build # Build Docker image
make docker-run   # Run Docker container
make compose-up   # Run both services dengan docker compose
make compose-down # Stop docker compose
make clean        # Hapus build artifacts
```

### 4. Docker

**Purpose:** Containerization untuk deployment.

| Command | Description |
|---------|-------------|
| `docker build -t logistics-backend .` | Build backend image |
| `docker run -p 8080:8080 --env-file .env logistics-backend` | Run backend container |
| `docker compose up --build` | Run both services |
| `docker compose down` | Stop all services |

**Key Files:**
- `Dockerfile` — Backend image definition
- `frontend/Dockerfile` — Frontend image definition
- `docker-compose.yml` — Multi-service orchestration

### 5. pytest

**Purpose:** Backend testing framework.

| Command | Description |
|---------|-------------|
| `uv run pytest` | Run all tests |
| `uv run pytest -v` | Run dengan verbose output |
| `uv run pytest --cov=backend` | Run dengan coverage |
| `uv run pytest --cov=backend --cov-report=term-missing` | Coverage dengan missing lines |
| `uv run pytest backend/tests/test_orchestrator.py` | Run specific test file |
| `uv run pytest -k "test_name"` | Run specific test |

**Key Files:**
- `backend/tests/` — Test directory
- `pyproject.toml` — pytest configuration

### 6. Git

**Purpose:** Version control.

**Branch Strategy:**
- `main` — Production-ready code
- `feature/*` — Feature branches
- `fix/*` — Bug fix branches

**Common Workflow:**
```bash
git checkout -b feature/new-feature
# ... make changes ...
git add .
git commit -m "feat: add new feature"
git push origin feature/new-feature
# Create PR on GitHub
```

---

## Development Workflow

### Adding a New Metric

1. **Define metric** di `backend/core/metrics.py`:
   ```python
   def _new_metric(frame: pd.DataFrame) -> MetricValue:
       # Implementation
       return value
   
   # Tambahkan ke METRICS dict
   MetricDefinition(
       name="new_metric",
       label="New Metric",
       compute=_new_metric,
       definition_text="description of metric",
       inclusion_rule="which rows are included",
       basis_count=_count_function,
       allowed_dimensions=ALL_DIMENSIONS,
   )
   ```

2. **Update schema** di `backend/core/schemas.py` (jika perlu)

3. **Add tests** di `backend/tests/`

4. **Run tests:** `uv run pytest`

### Adding a New API Endpoint

1. **Create router** di `backend/`:
   ```python
   from fastapi import APIRouter
   router = APIRouter(prefix="/api", tags=["new"])
   
   @router.get("/new-endpoint")
   def get_new():
       return {"status": "ok"}
   ```

2. **Create the router** in `backend/api/` and register it in `backend/main.py`:
   ```python
   from backend import new_api
   app.include_router(new_api.router, dependencies=_protected)
   ```

3. **Add tests**

4. **Run:** `make backend`

### Adding a New Frontend Page

1. **Create page** di `frontend/app/`:
   ```
   frontend/app/new-page/
   └── page.tsx
   ```

2. **Add to navigation** (jika ada)

3. **Run:** `make frontend`

---

## Testing Workflow

### Backend Tests

```bash
# Run all tests
uv run pytest

# Run dengan coverage
uv run pytest --cov=backend --cov-report=term-missing

# Run specific test file
uv run pytest backend/tests/test_orchestrator.py

# Run specific test
uv run pytest -k "test_query_tool"

# Run dengan verbose
uv run pytest -v
```

### Test Structure

```
backend/tests/
├── test_orchestrator.py    # Agent workflow tests
├── test_query_tool.py      # Query tool tests
├── test_filters.py         # Filter validation tests
├── test_reconciliation.py  # Data reconciliation tests
└── test_ask_turns.py       # Conversation history tests
```

### Writing Tests

```python
import pandas as pd
import pytest
from backend.tools.query import run_query
from backend.core.schemas import QueryStructuredRequest

def test_new_feature():
    request = QueryStructuredRequest(
        operation="query",
        metric="total_orders",
        dimensions=[],
        filters=[],
        time_range=None,
        sort=None,
        limit=100,
    )
    result = run_query(request, frame=test_dataframe)
    assert result.row_count == 1
```

---

## Deployment Workflow

### Railway Deployment

1. **Push ke GitHub** → Trigger auto-deploy

2. **Backend Service:**
   - Root Directory: `/`
   - Variables: `APP_USERNAME`, `APP_PASSWORD`, `LLM_API_KEY`, dll

3. **Frontend Service:**
   - Root Directory: `/frontend`
   - Variables: `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_API_USERNAME`, dll

4. **CORS Configuration:**
   - Set `FRONTEND_ORIGIN` di backend service

### Manual Deployment

```bash
# Build backend
docker build -t logistics-backend .

# Build frontend
cd frontend
docker build -t logistics-frontend .

# Run
docker compose up -d
```

---

## Troubleshooting

### Backend tidak bisa start

```bash
# Cek dependencies
uv sync

# Cek environment variables
cat .env

# Cek port
lsof -i :8080
```

### Frontend tidak bisa start

```bash
# Cek dependencies
cd frontend && npm install

# Cek environment variables
cat frontend/.env.local

# Cek port
lsof -i :3001
```

### LLM tidak merespons

```bash
# Cek API key
echo $LLM_API_KEY

# Test API
curl -H "Authorization: Bearer $LLM_API_KEY" \
     https://openrouter.ai/api/v1/models
```

### Tests gagal

```bash
# Run dengan verbose
uv run pytest -v

# Run specific test
uv run pytest -k "test_name" -v

# Cek coverage
uv run pytest --cov=backend --cov-report=term-missing
```

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────┐
│                    Development Commands                      │
├─────────────────────────────────────────────────────────────┤
│  make setup        → Install semua dependencies             │
│  make dev          → Run backend + frontend                 │
│  make test         → Run tests                              │
│  make lint         → Run linter                             │
│  make clean        → Hapus build artifacts                  │
├─────────────────────────────────────────────────────────────┤
│  Backend: http://localhost:8080                              │
│  Frontend: http://localhost:3001                             │
│  API Docs: http://localhost:8080/docs                        │
└─────────────────────────────────────────────────────────────┘
```
