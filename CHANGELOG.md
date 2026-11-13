# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
