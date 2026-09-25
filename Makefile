.DEFAULT_GOAL := help

BACKEND := backend
FRONTEND := frontend
UV_RUN := uv run --locked

.PHONY: help install dev dev-backend dev-frontend fmt lint typecheck test check

help:
	@echo "make install    Install locked backend and frontend dependencies"
	@echo "make dev        Run backend (127.0.0.1:8765) and frontend (127.0.0.1:5173)"
	@echo "make fmt        Format backend and frontend"
	@echo "make lint       Check formatting and lint"
	@echo "make typecheck  mypy --strict and tsc"
	@echo "make test       pytest and vitest"
	@echo "make check      lint + typecheck + test (quality gate)"

install:
	cd $(BACKEND) && uv sync --locked
	cd $(FRONTEND) && npm ci

dev:
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd $(BACKEND) && $(UV_RUN) python -m cv_masking --reload

dev-frontend:
	cd $(FRONTEND) && npm run dev

fmt:
	cd $(BACKEND) && $(UV_RUN) ruff format . && $(UV_RUN) ruff check --fix .
	cd $(FRONTEND) && npm run format

lint:
	cd $(BACKEND) && $(UV_RUN) ruff format --check . && $(UV_RUN) ruff check .
	cd $(FRONTEND) && npm run format:check && npm run lint

typecheck:
	cd $(BACKEND) && $(UV_RUN) mypy
	cd $(FRONTEND) && npm run typecheck

test:
	cd $(BACKEND) && $(UV_RUN) pytest
	cd $(FRONTEND) && npm test

check: lint typecheck test
