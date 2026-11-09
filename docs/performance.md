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

Measured on 2026-11-09 (UTC), warm file cache, one run each. Feature builds start from an
empty snapshot cache.

**Storage** (decimal megabytes). The typed Parquet tables take 136.6 MB (HI-Small) and
188.6 MB (LI-Small) on disk, against 509.7 MB and 697.7 MB for the source CSV files
(transactions plus accounts). The Pix layer adds 20.4 MB and 27.7 MB. In memory, the
HI-Small transactions table is about 229 MB: identifiers are `UInt32`, currencies and formats are
enums, and only amounts stay `Float64` (see ADR-004).

## Budgets

| Metric | Target | Status |
|---|---|---|
| Feature build, HI-Small, laptop | Under 10 minutes, under 8 GB RAM | **Met**: 28.2 s, 2,495 MiB |
| Score lookup, warm Lambda | p99 under 250 ms | Measured in week 3 |
| Lambda image | Under 300 MB | Measured in week 3 |
| Copilot | p95 under 30 s and under US$0.01 per case | Measured in week 4 |
| Full eval run | Under US$1 | Measured in week 4 |
