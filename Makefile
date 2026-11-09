# MuleTrace task runner. Every target is a thin wrapper around `uv run`, so the
# same commands work without make (copy the recipe line).

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

UV ?= uv

.PHONY: help
help:  ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

# ------------------------------------------------------------------ setup
.PHONY: install
install:  ## Install all dependency groups and activate the authorship hook
	$(UV) sync --all-extras --all-groups
	git config core.hooksPath .githooks

# ------------------------------------------------------------------ quality gates
.PHONY: lint
lint:  ## Ruff lint and format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

.PHONY: format
format:  ## Apply ruff formatting and safe fixes
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

.PHONY: typecheck
typecheck:  ## mypy --strict on src/
	$(UV) run mypy

.PHONY: test
test:  ## Unit and property tests with coverage
	$(UV) run pytest --cov --cov-report=term-missing --cov-fail-under=85

.PHONY: quality
quality:  ## Complexity, dead code, dependency and security checks
	$(UV) run xenon --max-absolute B --max-modules A --max-average A src
	$(UV) run vulture
	$(UV) run deptry src
	$(UV) run bandit -q -c pyproject.toml -r src
	$(UV) run pip-audit --skip-editable

.PHONY: check
check: lint typecheck test quality  ## Every gate CI runs
