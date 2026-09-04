# Documentation Index

Dokumentasi proyek AI Logistics Analytics Dashboard.

## Documents

| Document | Description |
|----------|-------------|
| [ONBOARDING.md](ONBOARDING.md) | Panduan setup development environment dan workflow |
| [WORKFLOW_AGENTS.md](WORKFLOW_AGENTS.md) | Arsitektur dan alur kerja AI agent |
| [DASHBOARD_DOCUMENTATION.md](DASHBOARD_DOCUMENTATION.md) | Panduan dashboard dan komponen frontend |
| [DATA_CORRECTNESS.md](DATA_CORRECTNESS.md) | Cara angka dashboard dan agent dibuktikan benar |

## Quick Links

- **Backend API Docs:** http://localhost:8080/docs (saat backend running)
- **Frontend:** http://localhost:3001
- **Repository:** [GitHub](<repository-url>)

## Project Structure

```
Logistic-web-dashboard/
├── backend/                 # Python FastAPI backend
│   ├── main.py             # Application composition root
│   ├── api/                # FastAPI routers: ask, auth, query, forecast
│   ├── agents/             # Deep agent assembly and orchestration
│   ├── tools/              # Governed query, forecast, and agent tools
│   ├── observe/            # Optional Langfuse tracing adapter
│   ├── core/               # Schemas, metrics, ingestion, answers, rules
│   └── tests/              # Backend tests
├── frontend/               # Next.js frontend
│   ├── app/                # App router pages
│   └── lib/                # Shared utilities
├── docs/                   # This documentation
├── Makefile                # Development shortcuts
├── pyproject.toml          # Python dependencies
└── docker-compose.yml      # Multi-service orchestration
```
