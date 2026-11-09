# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
