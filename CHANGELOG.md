# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-11-14

Week 4: investigation copilot and its evaluation.

### Added
- Case evidence and structured case files in which every claim cites its transfers, amounts,
  dates and accounts.
- Deterministic fact checker that rejects drafts with unknown or mismatched facts, unknown
  typologies, actions or policies, recommendations to release funds, or contact details.
- Sourced policy library (eight entries) with topic lookup.
- Model-free template baseline, a single-call baseline and a three-agent copilot (evidence,
  typology, report) on the Bedrock Converse API with tool use, token budget and tool-round cap.
- Copilot Lambda and a Bedrock guardrail (prompt attacks, contact details in outputs, releasing
  funds as a denied topic) in a new agents stack; optional OIDC role for evaluations.
- 150-case HI-Small gold set built from AMLworld's patterns file, copilot metrics, checker
  perturbation tests, a prompt-injection suite, a release gate and an evaluation workflow.
- Binary LLM judge with calibration against human labels (labels pending).
- `muletrace copilot gold` and `muletrace copilot eval`; copilot section in the evaluation
  report; ADR-011; week-4 audit.

### Changed
- PyYAML is a runtime dependency (the copilot reads its policy library in the Lambda).

### Security
- tornado upgraded to 6.6.1 (CVE-2026-126347), through the notebooks group.

## [0.2.0] - 2026-11-13

Week 3: production path on AWS.

### Added
- MED-inspired fund-flow tracer with known-answer and conservation tests, and its evaluation
  against AMLworld's laundering labels.
- Scoring Lambda (arm64 image) reading precomputed features from DynamoDB with a lossless
  encoding, capped display probabilities and SHAP reason codes; batch/online parity test.
- Model loading from S3 at cold start and approval-driven promotion from the model registry.
- SageMaker Spot training job and model-package registration (`PendingManualApproval`), running
  the same final-training function as `muletrace models train-final`.
- Daily scoring workflow (Step Functions: build snapshot, score and publish) and SQS replay of
  transfers.
- CDK stacks for storage, serving, training, pipeline and cost guards, checked by cdk-nag in CI;
  OIDC deployment workflow with manual approval; container build, size and vulnerability scan.
- Runbook, GitHub OIDC bootstrap template, ADR-009 and ADR-010, week-3 audit.

### Changed
- The CLI is split into one module per command group.

### Fixed
- The promotion Lambda no longer imports LightGBM through the artefact module.

## [0.1.0] - 2026-11-09

Week 2: features, models and honest validation.

### Added
- Point-in-time account features (flows over 24 h, 72 h and 7 days, forwarding speed,
  structuring signals, inflow mix) and graph features (degrees, PageRank, sender aggregates,
  neighbour labels confirmed before the as-of time), cached per configuration hash.
- LightGBM training with negative subsampling, a six-point search chosen on the first fold,
  isotonic calibration and a portable model artefact.
- Rolling-origin backtest of the model ladder (hand-set rules, tuned rules, behaviour-only
  LightGBM, LightGBM with graph features) with paired bootstrap intervals, expected-cost curves,
  calibration diagnostics, error slices and SHAP reason codes.
- Label-delay sensitivity sweep and a reproduction of AMLworld's transaction-level task.
- Error-analysis notebook.
- Documents rendered from generated results (`muletrace docs render`), with a test that fails
  when a published number drifts from its source.
- ADR-007 (graph features) and ADR-008 (experiment tracking).

### Fixed
- Transaction-level pair features used a string key whose rolling groups came back in a
  different order; a row-alignment guard caught it before any result was published.

## [0.0.1] - 2026-11-09

Week 1: foundation, data and the business case.

### Added
- Project scaffold: packaging with uv, ruff, mypy (strict), pytest, pre-commit.
- Commit-message hook and CI scan that reject AI attribution trailers.
- CI workflow: lint, types, tests with coverage floor, complexity, dead code, dependency,
  security and secret scanning.
- Business case, decision map and ADRs 001–006.
- AMLworld ingestion with stable transaction and account identifiers, inferred exchange rates,
  pattern linking, pandera contracts and a SHA-256 manifest; CDLA-Sharing-1.0 licence text.
- Mule target with delayed confirmation.
- Pix-layer simulator v0 calibrated to BCB open-data aggregates.
- Data card and generated dataset profile.
- Point-in-time snapshot builder with look-ahead and label-delay property tests.
- Alert-budget decision metrics and the rules baseline on the temporal hold-out.
- Exploratory notebook and its tested analysis helpers.
- In-process measurement of wall time and peak memory; performance log; week-1 audit.
