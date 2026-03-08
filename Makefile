# Makefile — Aria development shortcuts
# Usage: make test | make test-quick | make test-integration | make build | make up

COMPOSE = docker compose
API_CONTAINER = aria-api

# ============================================================================
# Testing
# ============================================================================

.PHONY: test test-quick test-integration test-arch

test: ## Run all tests inside Docker
	$(COMPOSE) exec $(API_CONTAINER) pytest tests/ -v --tb=short

test-quick: ## Run unit + arch tests only (no network)
	pytest tests/test_architecture.py tests/test_imports.py -v --tb=short

test-integration: ## Run live integration tests (requires running stack)
	pytest tests/ -v --tb=short -m integration

test-arch: ## Run architecture compliance tests
	pytest tests/test_architecture.py -v --tb=short

test-coverage: ## Run tests with coverage report
	$(COMPOSE) exec $(API_CONTAINER) pytest tests/ --cov=src/api --cov-report=term-missing

# ============================================================================
# Docker
# ============================================================================

.PHONY: build up down logs restart check-env

build: ## Build all containers
	$(COMPOSE) build

check-env: ## Bootstrap stacks/brain/.env from .env.example if absent (safe no-op when .env exists)
	@bash scripts/first-run.sh --auto

up: check-env ## Start all services (auto-bootstraps .env on fresh clone)
	$(COMPOSE) up -d

down: ## Stop all services
	$(COMPOSE) down

logs: ## Tail logs
	$(COMPOSE) logs -f --tail=50

restart: ## Restart API container
	$(COMPOSE) restart $(API_CONTAINER)

# ============================================================================
# Development
# ============================================================================

.PHONY: lint format check verify-deploy watchdog hooks security-scan audit-deps guardrail

lint: security-scan ## Run linting + security scans
	ruff check aria_skills/ aria_agents/ aria_models/ src/
	@echo "Lint and security scans complete"

security-scan: ## Run SAST security scan (bandit)
	bandit -r aria_skills/ aria_engine/ src/ -c pyproject.toml -f json -o bandit-report.json || true
	@echo "Bandit scan complete. See bandit-report.json"

audit-deps: ## Run dependency vulnerability scan (pip-audit)
	pip-audit --format json --output pip-audit-report.json || true
	@echo "Dependency audit complete. See pip-audit-report.json"

format: ## Auto-format code
	ruff format aria_skills/ aria_agents/ aria_models/ src/

check: lint test-quick ## Lint + quick tests

verify-deploy: ## Run deployment verification script
	./tests/e2e/verify_deployment.sh --quick

guardrail: ## Fail-fast check for Mac/Web->Docker API path auth & CSRF regressions
	python tests/integration/guardrail_web_api_path.py

watchdog: ## Run one health watchdog cycle for aria-api
	./scripts/health_watchdog.sh aria-api

hooks: ## Install git pre-commit hook
	./scripts/install_hooks.sh

# ============================================================================
# Help
# ============================================================================

.DEFAULT_GOAL := help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
