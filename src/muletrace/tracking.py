"""Experiment tracking: MLflow when configured, a local JSON Lines log otherwise.

When ``MLFLOW_TRACKING_URI`` is set (for example to a SageMaker managed MLflow tracking server),
every run is logged to MLflow. Without it, runs are appended to
``<artifacts>/experiments/<experiment>.jsonl``, which needs no server and no database. MLflow 3
keeps its file-system backend in maintenance mode, so the local fallback avoids depending on it
(ADR-008).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RunLogger:
    """Log one record per training run to MLflow or to a local file."""

    def __init__(self, experiment: str, local_dir: Path) -> None:
        self.experiment = experiment
        self.local_path = local_dir / f"{experiment}.jsonl"
        self.uses_mlflow = bool(os.environ.get("MLFLOW_TRACKING_URI"))

    def log(
        self,
        run_name: str,
        params: Mapping[str, Any],
        metrics: Mapping[str, float],
        tags: Mapping[str, str] | None = None,
    ) -> None:
        """Record one run."""
        if self.uses_mlflow:
            self._log_mlflow(run_name, params, metrics, tags or {})
        else:
            self._log_local(run_name, params, metrics, tags or {})

    def _log_local(
        self,
        run_name: str,
        params: Mapping[str, Any],
        metrics: Mapping[str, float],
        tags: Mapping[str, str],
    ) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "logged_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
            "experiment": self.experiment,
            "run_name": run_name,
            "params": dict(params),
            "metrics": dict(metrics),
            "tags": dict(tags),
        }
        with self.local_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")

    def _log_mlflow(
        self,
        run_name: str,
        params: Mapping[str, Any],
        metrics: Mapping[str, float],
        tags: Mapping[str, str],
    ) -> None:
        import mlflow  # noqa: PLC0415 - optional dependency (the `tracking` extra)

        mlflow.set_experiment(self.experiment)
        with mlflow.start_run(run_name=run_name, tags=dict(tags)):
            mlflow.log_params({key: str(value) for key, value in params.items()})
            mlflow.log_metrics(dict(metrics))
