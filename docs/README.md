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
│   ├── main.py             # Application entry point
│   ├── agent.py            # Deep agent assembly, system prompts, threads
│   ├── agent_tools.py      # query / forecast / decline tools
│   ├── orchestrator.py     # Runs the agent, assembles AskResponse
│   ├── answers.py          # Answer prose and explainability
│   ├── grounding.py        # Every stated figure traced to a tool result
│   ├── llm.py              # Chat model construction and credentials
│   ├── query_tool.py       # Structured query execution
│   ├── forecast.py         # Demand forecasting
│   ├── metrics.py          # Metric definitions (single source of truth)
│   ├── status_rules.py     # Order status semantics
│   ├── ingestion.py        # Validated, read-only CSV load
│   ├── schemas.py          # Pydantic contracts
│   └── tests/              # Backend tests
├── frontend/               # Next.js frontend
│   ├── app/                # App router pages
│   └── lib/                # Shared utilities
├── docs/                   # This documentation
├── Makefile                # Development shortcuts
├── pyproject.toml          # Python dependencies
└── docker-compose.yml      # Multi-service orchestration
```
