"""``muletrace monitor …``: run the drift check locally on cached snapshots."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import TYPE_CHECKING

from muletrace.cli._common import Groups, write_generated
from muletrace.settings import Settings

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

# Library imports live inside handlers so that `muletrace --help` stays fast.
# ruff: noqa: PLC0415


def _drift(args: argparse.Namespace, settings: Settings) -> int:
    import polars as pl

    from muletrace.cli.models import experiment_config
    from muletrace.config import CONFIG_DIR, load_config
    from muletrace.features.build import build_snapshots
    from muletrace.models.artifact import load_artifact
    from muletrace.monitoring.drift import DriftConfig, drift_report
    from muletrace.monitoring.job import scored_columns
    from muletrace.serving.batch import score_snapshot

    config = load_config(DriftConfig, CONFIG_DIR / "monitoring.yaml")
    experiment = experiment_config()
    days = [config.reference_day, *args.days]
    snapshots = build_snapshots(
        settings.processed_dir / config.dataset,
        settings.features_dir,
        [datetime.fromisoformat(day) for day in days],
        experiment.labels,
        experiment.features,
    )
    scores = score_snapshot(
        snapshots, load_artifact(settings.artifacts_dir / "models" / config.dataset)
    )

    def columns(day: str) -> dict[str, NDArray[np.float64]]:
        moment = datetime.fromisoformat(day)
        return scored_columns(
            snapshots.filter(pl.col("as_of") == moment),
            scores.filter(pl.col("as_of") == moment),
            config.features,
        )

    reference = columns(config.reference_day)
    report = {
        "dataset": config.dataset,
        "reference_day": config.reference_day,
        "thresholds": {"psi_alert": config.psi_alert, "ks_alert": config.ks_alert},
        "report_only": list(config.report_only),
        "days": {day: drift_report(reference, columns(day), config) for day in args.days},
    }
    write_generated(f"drift_{config.dataset}.yaml", report, "muletrace monitor drift")
    return 0


def register(groups: Groups) -> None:
    """Add the ``monitor`` group."""
    monitor = groups.add_parser("monitor", help="Production monitoring checks, run locally")
    sub = monitor.add_subparsers(dest="command", required=True)
    drift = sub.add_parser("drift", help="Drift of later snapshots against the reference day")
    drift.add_argument("--days", nargs="+", required=True, help="Days to compare, YYYY-MM-DD")
    drift.set_defaults(handler=_drift)
