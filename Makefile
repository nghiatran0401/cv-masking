.DEFAULT_GOAL := help

BACKEND := backend
FRONTEND := frontend
UV_RUN := uv run --locked

.PHONY: help setup install hooks guard dev dev-backend dev-frontend build eval fmt lint typecheck test check

help:
	@echo "make setup      First time on a laptop: project venv, locked dependencies, then the production UI"
	@echo "make install    Create backend/.venv with uv-managed Python 3.12 and install locked dependencies"
	@echo "make build      Production UI into the Python package (HR runtime does not need Node)"
	@echo "make guard      Refuse tracked documents, images, data files, and logs"
	@echo "make dev        Run backend (127.0.0.1:8765) and frontend (127.0.0.1:5173)"
	@echo "make fmt        Format backend and frontend"
	@echo "make lint       Check formatting and lint"
	@echo "make typecheck  mypy --strict and tsc"
	@echo "make test       pytest, vitest, and Playwright"
	@echo "make eval       Synthetic metadata-only evaluation (never authorized / real CVs)"
	@echo "make check      guard + lint + typecheck + build + test (quality gate)"

setup: install build

install: hooks
	cd $(BACKEND) && uv python install 3.12
	cd $(BACKEND) && uv venv --python 3.12 --managed-python --allow-existing .venv
	cd $(BACKEND) && uv sync --locked --python 3.12 --managed-python
	cd $(FRONTEND) && npm ci
	cd $(FRONTEND) && npx playwright install chromium

hooks:
	git config core.hooksPath scripts/git-hooks

guard:
	scripts/check-repo-files.sh --all

dev:
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd $(BACKEND) && $(UV_RUN) python -m cv_masking --reload

dev-frontend:
	cd $(FRONTEND) && npm run dev

build:
	cd $(FRONTEND) && npm run build
	rm -rf $(BACKEND)/src/cv_masking/static
	mkdir -p $(BACKEND)/src/cv_masking/static
	cp -R $(FRONTEND)/dist/. $(BACKEND)/src/cv_masking/static/

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
	cd $(BACKEND) && $(UV_RUN) python scripts/run_pytest.py
	cd $(FRONTEND) && npm test
	cd $(FRONTEND) && npx playwright test

eval:
	cd $(BACKEND) && $(UV_RUN) python -m cv_masking.evaluation

check: guard lint typecheck build test
