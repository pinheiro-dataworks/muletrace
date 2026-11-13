# ADR-008: Experiment tracking — MLflow when configured, JSON Lines otherwise

- Status: Accepted
- Date: 2026-11-09

## Context

The build plan asks for the model ladder to be tracked in MLflow, with SageMaker managed MLflow
in the cloud and a local fallback. MLflow 3 keeps its file-system tracking backend in
maintenance mode: writing to `./mlruns` raises an error unless `MLFLOW_ALLOW_FILE_STORE=true` is
set, and its recommended local backend (SQLite) needs the full `mlflow` package with SQLAlchemy.
Pulling a database backend into a laptop workflow to log a few dozen runs is not worth it.

## Decision

`muletrace.tracking.RunLogger` logs every training run:

- to **MLflow** when `MLFLOW_TRACKING_URI` is set (for example the ARN of a SageMaker managed
  MLflow tracking server); `mlflow-skinny` is an optional extra (`tracking`);
- otherwise to `artifacts/experiments/<experiment>.jsonl`, one JSON record per run with the
  parameters, metrics and tags.

## Consequences

- Local runs need no server and no database, and the run log is plain text that can be diffed.
- The cloud training job logs to managed MLflow with no code change.
- The local log has no UI; the published numbers come from `docs/generated/` anyway, so the run
  log is an audit trail rather than the source of results.
