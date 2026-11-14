# Performance

Measure first, then optimise. Every number here was measured; nothing is estimated. Each CLI
command logs its own wall time and peak resident memory (`muletrace.perf`), which is where the
figures below come from.

## Machine

| | |
|---|---|
| CPU | AMD Ryzen 5 6600H (6 cores, 12 threads) |
| Memory | 15.2 GB |
| OS | Windows 11 |
| Python | 3.12.15, Polars 2.1.0 |

## Data pipeline (HI-Small and LI-Small together)

| Stage | Command | Wall time | Peak memory |
|---|---|---:|---:|
| Ingestion: CSV → validated Parquet, both datasets | `muletrace data prepare` | 13.4 s | 2,510 MiB |
| Pix layer, both datasets | `muletrace data simulate-pix` | 3.8 s | 1,657 MiB |
| Dataset profile | `muletrace data profile` | 1.2 s | 1,673 MiB |
| Rules baseline, 3 snapshots × 2 datasets | `muletrace models rules` | 5.2 s | 1,349 MiB |
| Feature build, HI-Small, 8 snapshots | `muletrace features build --datasets HI-Small` | 28.2 s | 2,495 MiB |
| Feature build, LI-Small, 8 snapshots | `muletrace features build --datasets LI-Small` | 37.2 s | 3,373 MiB |
| Backtest, LI-Small (4 folds × 4 models, search, 1,000-replicate bootstrap, report) | `muletrace models backtest --datasets LI-Small` | 834.2 s | 2,675 MiB |
| Transaction-level external check, both datasets | `muletrace models transaction-check` | 227.7 s | 2,853 MiB |
| Tracer evaluation, every accepted dispute of both datasets (70 traces) | `muletrace trace evaluate` | 8.7 s | 1,454 MiB |
| Label-delay sweep, HI-Small (5 delays × 3 folds × 2 models, rebuilding snapshots per delay) | `muletrace models delay-sweep` | 1,203.9 s | 4,367 MiB |

Measured on 2026-11-09 (UTC), warm file cache, one run each. Feature builds start from an
empty snapshot cache; the backtest reads cached snapshots. The HI-Small backtest was not timed
in a clean run (its first run was interrupted by a report-serialisation bug, since fixed), so
only LI-Small is listed. Training uses `num_threads: 6` throughout.

**Where the backtest time goes.** LightGBM fits are fast because negatives are subsampled to 20%
(a fold trains on up to about 270,000 rows instead of 1.3 million). The paired bootstrap was
timed separately on the HI-Small hold-out predictions: about 0.25 s per replicate for four models
and three snapshots, so roughly four minutes for 1,000 replicates. The tuned-rules grid evaluates
54 threshold combinations per fold and was not timed on its own.

**Storage** (decimal megabytes). The typed Parquet tables take 136.6 MB (HI-Small) and
188.6 MB (LI-Small) on disk, against 509.7 MB and 697.7 MB for the source CSV files
(transactions plus accounts). The Pix layer adds 20.4 MB and 27.7 MB. In memory, the
HI-Small transactions table is about 229 MB: identifiers are `UInt32`, currencies and formats are
enums, and only amounts stay `Float64` (see ADR-004).

## Scoring latency (local, in-process)

From `scripts/benchmark_scoring.py`, written to
[`docs/generated/serving_benchmark.yaml`](generated/serving_benchmark.yaml): the HI-Small model
scored 2,000 times against the 9 September snapshot through the same `ScoringService` the Lambda
uses, with an in-memory feature store.

| Measure | Value |
|---|---:|
| Model artefact size | 1.5 MB (1,496,302 bytes) |
| Artefact load time | 44.0 ms |
| Latency p50 / p95 / p99 | 5.6 / 6.3 / 7.2 ms |

This excludes the network, API Gateway, Lambda start-up and the DynamoDB read. Deployed
latency, cold starts, the image size and memory tuning are measured after the first deployment
(see the runbook); until then they are not reported.

## Budgets

| Metric | Target | Status |
|---|---|---|
| Feature build, HI-Small, laptop | Under 10 minutes, under 8 GB RAM | **Met**: 28.2 s, 2,495 MiB |
| Score lookup, warm Lambda | p99 under 250 ms | Not yet measured: needs a deployment. In-process p99 is 7.2 ms |
| Lambda image | Under 300 MB | Not yet measured locally (Docker unavailable); the CI container job records it |
| Copilot | p95 under 30 s and under US$0.01 per case | Measured in week 4 |
| Full eval run | Under US$1 | Measured in week 4 |
