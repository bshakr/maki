# maki — bootstrap & dev orchestration.
#
# Quickstart:  make setup && make dev
#
# Design: reads are auto, user-shell steps are PRINTED. `make setup` only does safe, idempotent
# things; anything needing your interactive shell (AWS creds via Granted's `assume`) or a daemon
# (Docker) is detected and printed as the exact command to run — never run for you. Absent AWS
# creds never fail the build: they're needed at request time, not to boot.

SHELL := /bin/bash

# --- Paths (match the repo's hand-typed steps exactly) ---
VENV        := backend/.venv
PY          := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
ALEMBIC     := $(VENV)/bin/alembic
PYTHON311   := python3.11
CONFIG      := maki.config.yaml
CONFIG_EX   := maki.config.example.yaml

BACKEND_PORT := 8787
FRONTEND_PORT := 5173
DB_PORT       := 5544
DB_SERVICE    := maki-postgres

# AWS profile printed in `assume` hints. Override: `make doctor AWS_PROFILE_HINT=Org/Dev` or export it.
# Pick a profile with Amplify read access if you configure an Amplify app (read-only
# permission sets often lack amplify:GetBranch).
AWS_PROFILE_HINT ?= <your-profile>

# ✓/✗ markers
OK   := \033[32m✓\033[0m
BAD  := \033[31m✗\033[0m
WARN := \033[33m!\033[0m

.DEFAULT_GOAL := help
.PHONY: help setup dev doctor venv backend-deps frontend-deps config db-up migrate \
        backend frontend test check clean

help: ## Show this help
	@echo "maki — make targets:"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Typical:  make setup && make dev"

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

setup: venv backend-deps config db-up migrate frontend-deps ## One-command bootstrap (idempotent)
	@echo
	@echo -e "$(OK) setup complete."
	@echo "Next: get AWS creds into your shell, then run the app:"
	@echo -e "    \033[36massume $(AWS_PROFILE_HINT)\033[0m            # Granted — loads creds into THIS shell"
	@echo -e "    \033[36mexport GITHUB_TOKEN=\"\$$(gh auth token)\"\033[0m   # optional: deploy timelines + PR enrichment"
	@echo -e "    \033[36mmake dev\033[0m                       # backend (:$(BACKEND_PORT)) + frontend (:$(FRONTEND_PORT))"

venv: ## Create the backend virtualenv (backend/.venv) if absent
	@if [ -x "$(PY)" ]; then \
		echo -e "$(OK) venv present ($(VENV))"; \
	else \
		echo "Creating venv at $(VENV) ..."; \
		$(PYTHON311) -m venv $(VENV) && echo -e "$(OK) venv created"; \
	fi

backend-deps: venv ## Install backend deps (requirements-dev.txt + editable install)
	@echo "Installing backend deps ..."
	@$(PIP) install -q --upgrade pip >/dev/null
	@cd backend && .venv/bin/pip install -q -r requirements-dev.txt
	@cd backend && .venv/bin/pip install -q -e .
	@echo -e "$(OK) backend deps installed"

frontend-deps: ## Install frontend deps (npm ci if lockfile present, else npm install)
	@echo "Installing frontend deps ..."
	@if [ -f frontend/package-lock.json ]; then \
		cd frontend && npm ci --silent; \
	else \
		cd frontend && npm install --silent; \
	fi
	@echo -e "$(OK) frontend deps installed"

config: ## Create maki.config.yaml from the example (only if absent)
	@if [ -f "$(CONFIG)" ]; then \
		echo -e "$(OK) config present ($(CONFIG))"; \
	else \
		cp "$(CONFIG_EX)" "$(CONFIG)"; \
		echo -e "$(WARN) created $(CONFIG) from $(CONFIG_EX) — edit it (aws.region / aws.ecsCluster are required)"; \
	fi

db-up: ## Start maki's Postgres (docker compose); prints how to start Docker if the daemon is down
	@if ! docker info >/dev/null 2>&1; then \
		echo -e "$(BAD) Docker daemon not running — start it, then re-run \033[36mmake db-up\033[0m"; \
		echo "    (Docker Desktop / OrbStack — open the app or run its CLI start command)"; \
	else \
		docker compose up -d $(DB_SERVICE) >/dev/null && echo -e "$(OK) $(DB_SERVICE) up on localhost:$(DB_PORT)"; \
	fi

migrate: ## Apply alembic migrations (needs Postgres up)
	@if ! nc -z 127.0.0.1 $(DB_PORT) >/dev/null 2>&1; then \
		echo -e "$(BAD) ledger DB unreachable at 127.0.0.1:$(DB_PORT) — run \033[36mmake db-up\033[0m first"; \
	else \
		cd backend && .venv/bin/alembic upgrade head && echo -e "$(OK) migrations at head"; \
	fi

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

dev: ## Run backend + frontend together (Ctrl-C stops both)
	@$(MAKE) --no-print-directory _aws-hint
	@echo -e "Starting backend (:$(BACKEND_PORT)) + frontend (:$(FRONTEND_PORT)) — Ctrl-C to stop both."
	@trap 'kill 0' INT TERM EXIT; \
		( cd backend && MAKI_RELOAD=1 .venv/bin/python -m maki.server ) & \
		( cd frontend && npm run dev ) & \
		wait

backend: ## Run only the backend (uvicorn, :8787)
	@$(MAKE) --no-print-directory _aws-hint
	@cd backend && MAKI_RELOAD=1 .venv/bin/python -m maki.server

frontend: ## Run only the frontend (Vite, :5173)
	@cd frontend && npm run dev

# Advisory only: print the assume command if creds are absent. Never fails — boot needs no creds.
.PHONY: _aws-hint
_aws-hint:
	@if ! aws sts get-caller-identity >/dev/null 2>&1; then \
		echo -e "$(WARN) No AWS creds in this shell — /api endpoints will 503 until you run:"; \
		echo -e "    \033[36massume $(AWS_PROFILE_HINT)\033[0m   (in THIS shell, then restart the backend here)"; \
	fi

# ---------------------------------------------------------------------------
# Doctor (preflight report — always exits 0)
# ---------------------------------------------------------------------------

doctor: ## Preflight: one friendly line per dependency (always exits 0)
	@echo "maki doctor:"
	@if [ -f "$(CONFIG)" ]; then \
		echo -e "  $(OK) config        $(CONFIG) present"; \
	else \
		echo -e "  $(BAD) config        missing — run \033[36mmake config\033[0m (copies $(CONFIG_EX))"; fi
	@if [ -x "$(PY)" ]; then \
		echo -e "  $(OK) venv          $(VENV)"; \
	else \
		echo -e "  $(BAD) venv          missing — run \033[36mmake setup\033[0m"; fi
	@if [ -d frontend/node_modules ]; then \
		echo -e "  $(OK) frontend deps node_modules present"; \
	else \
		echo -e "  $(BAD) frontend deps missing — run \033[36mmake setup\033[0m"; fi
	@if docker info >/dev/null 2>&1; then \
		echo -e "  $(OK) docker        daemon running"; \
	else \
		echo -e "  $(BAD) docker        daemon not running — start Docker Desktop / OrbStack"; fi
	@if nc -z 127.0.0.1 $(DB_PORT) >/dev/null 2>&1; then \
		echo -e "  $(OK) postgres      reachable on 127.0.0.1:$(DB_PORT)"; \
	else \
		echo -e "  $(BAD) postgres      unreachable on 127.0.0.1:$(DB_PORT) — run \033[36mmake db-up\033[0m"; fi
	@if [ -x "$(ALEMBIC)" ] && nc -z 127.0.0.1 $(DB_PORT) >/dev/null 2>&1; then \
		if cd backend && .venv/bin/alembic current 2>/dev/null | grep -q '(head)'; then \
			echo -e "  $(OK) migrations    at head"; \
		else \
			echo -e "  $(BAD) migrations    pending — run \033[36mmake migrate\033[0m"; fi; \
	else \
		echo -e "  $(WARN) migrations    skipped (venv or DB not ready)"; fi
	@if aws sts get-caller-identity >/dev/null 2>&1; then \
		echo -e "  $(OK) aws creds     caller identity resolves"; \
	else \
		echo -e "  $(WARN) aws creds     missing/expired — run \033[36massume $(AWS_PROFILE_HINT)\033[0m (then restart the backend in that shell)"; fi
	@if [ -n "$$GITHUB_TOKEN" ] || gh auth token >/dev/null 2>&1; then \
		echo -e "  $(OK) github token  available"; \
	else \
		echo -e "  $(WARN) github token  unset — timelines/PR enrichment empty. export GITHUB_TOKEN=\"\$$(gh auth token)\""; fi

# ---------------------------------------------------------------------------
# Test / clean
# ---------------------------------------------------------------------------

test: ## Run backend (pytest) + frontend (vitest) tests
	@cd backend && .venv/bin/pytest
	@cd frontend && npm run test

check: ## Lint + typecheck + tests, both stacks (the "is it green" gate)
	@cd backend && .venv/bin/ruff check src tests
	@cd frontend && npm run lint
	@cd frontend && npm run typecheck
	@$(MAKE) --no-print-directory test

clean: ## Remove venv + node_modules (leaves config + the Postgres volume intact)
	@rm -rf $(VENV) frontend/node_modules
	@echo -e "$(OK) removed $(VENV) and frontend/node_modules"
