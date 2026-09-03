.PHONY: setup dev backend frontend test lint docker-build docker-run clean

# Setup
setup:
	uv sync
	cd frontend && npm install

# Development
dev: setup
	@echo "Starting backend and frontend..."
	@make -j2 backend frontend

backend:
	uv run uvicorn backend.main:app --reload --port 8080

frontend:
	cd frontend && npm run dev

# Testing
test:
	uv run pytest

test-cov:
	uv run pytest --cov=backend --cov-report=term-missing

# Linting
lint:
	cd frontend && npm run lint

# Docker (the root image is the backend only; use compose-up for both services)
docker-build:
	docker build -t logistics-backend .

docker-run:
	docker run -p 8080:8080 --env-file .env logistics-backend

compose-up:
	docker compose up --build

compose-down:
	docker compose down

# Clean
clean:
	rm -rf .venv __pycache__ .pytest_cache .coverage
	rm -rf frontend/node_modules frontend/.next frontend/out
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
