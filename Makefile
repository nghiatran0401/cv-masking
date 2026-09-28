.DEFAULT_GOAL := help

BACKEND := backend
FRONTEND := frontend
UV_RUN := uv run --locked

.PHONY: help install hooks guard dev dev-backend dev-frontend build fmt lint typecheck test check

help:
	@echo "make install    Install locked dependencies, Playwright Chromium, and the git pre-commit file guard"
	@echo "make build      Production UI into the Python package (HR runtime does not need Node)"
	@echo "make guard      Refuse tracked documents, images, data files, and logs"
	@echo "make dev        Run backend (127.0.0.1:8765) and frontend (127.0.0.1:5173)"
	@echo "make fmt        Format backend and frontend"
	@echo "make lint       Check formatting and lint"
	@echo "make typecheck  mypy --strict and tsc"
	@echo "make test       pytest, vitest, and Playwright"
	@echo "make check      guard + lint + typecheck + build + test (quality gate)"

install: hooks
	cd $(BACKEND) && uv sync --locked
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

check: guard lint typecheck build test
