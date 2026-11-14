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

.PHONY: all
all: install data baseline features experiments  ## From a fresh clone to a trained, evaluated model

.PHONY: check
check: lint typecheck test quality  ## Every gate CI runs

# ------------------------------------------------------------------ data and models
.PHONY: data
data:  ## Download missing files, verify checksums, prepare Parquet, add the Pix layer, profile
	$(UV) run muletrace data download
	$(UV) run muletrace data verify
	$(UV) run muletrace data prepare
	$(UV) run muletrace data simulate-pix
	$(UV) run muletrace data profile

.PHONY: baseline
baseline:  ## Score the rules baseline on the temporal hold-out
	$(UV) run muletrace models rules

.PHONY: features
features:  ## Build and cache point-in-time feature snapshots
	$(UV) run muletrace features build

.PHONY: experiments
experiments:  ## Backtest the model ladder, label-delay sweep and the external check
	$(UV) run muletrace models backtest
	$(UV) run muletrace models delay-sweep
	$(UV) run muletrace models transaction-check

.PHONY: image
image:  ## Build the arm64 scoring image (needs Docker with buildx)
	$(UV) export --frozen --no-dev --no-emit-project --extra aws -o docker/requirements.txt
	docker buildx build --platform linux/arm64 -f docker/lambda.Dockerfile -t muletrace-scorer --load .

ALERT_EMAIL ?= alerts@example.invalid

.PHONY: synth
synth:  ## Synthesise every CDK stack and run cdk-nag
	$(UV) run --group infra pytest tests/infra -q
	npx -y aws-cdk@2 synth --quiet -c alert_email=$(ALERT_EMAIL)

.PHONY: deploy
deploy:  ## Deploy every stack with your AWS profile (set ALERT_EMAIL to a real address)
	$(UV) export --frozen --no-dev --no-emit-project --extra aws -o docker/requirements.txt
	$(UV) export --frozen --no-dev --no-emit-project --extra pipeline --extra aws -o docker/requirements-batch.txt
	npx -y aws-cdk@2 deploy --all -c alert_email=$(ALERT_EMAIL)

.PHONY: teardown
teardown:  ## Delete every stack, including the data bucket's objects
	npx -y aws-cdk@2 destroy --all --force

.PHONY: notebooks
notebooks:  ## Re-execute the notebooks in place (outputs are committed)
	cd notebooks && $(UV) run jupyter nbconvert --to notebook --execute --inplace 01_eda.ipynb 02_error_analysis.ipynb
