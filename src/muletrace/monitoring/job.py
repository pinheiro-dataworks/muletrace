"""The weekly drift Lambda: compare a scored snapshot with the reference one and publish.

Inputs are what the daily workflow already writes to ``DATA_BUCKET``
(``snapshots/<dataset>/<day>.parquet`` and ``scores/<dataset>/<day>.parquet``). The job puts
the statistics in CloudWatch (namespace ``MuleTrace/Drift``), where two alarms notify the alerts
topic, and stores the full report as ``monitoring/drift/<dataset>/<day>.json``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Final

import numpy as np
import polars as pl
from numpy.typing import NDArray

from muletrace.config import CONFIG_DIR, load_config
from muletrace.monitoring.drift import DriftConfig, cloudwatch_metrics, drift_report

NAMESPACE: Final = "MuleTrace/Drift"
WORK_DIR = Path("/tmp/muletrace-drift")  # noqa: S108  # nosec B108


def scored_columns(
    snapshot: pl.DataFrame, scores: pl.DataFrame, features: tuple[str, ...]
) -> dict[str, NDArray[np.float64]]:
    """The monitored features and the probability, aligned by account."""
    joined = snapshot.select("account_id", *features).join(
        scores.select("account_id", "probability"), on="account_id", how="inner"
    )
    return {
        name: joined[name].cast(pl.Float64).fill_null(np.nan).to_numpy()
        for name in (*features, "probability")
    }


def _download(
    s3: Any,  # noqa: ANN401 - boto3 client
    bucket: str,
    dataset: str,
    day: str,
    work_dir: Path,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    frames = []
    for kind in ("snapshots", "scores"):
        local = work_dir / f"{kind}-{day}.parquet"
        s3.download_file(bucket, f"{kind}/{dataset}/{day}.parquet", str(local))
        frames.append(pl.read_parquet(local))
    return frames[0], frames[1]


def drift_step(
    event: dict[str, Any],
    s3: Any,  # noqa: ANN401 - boto3 clients
    cloudwatch: Any,  # noqa: ANN401
    work_dir: Path = WORK_DIR,
) -> dict[str, Any]:
    """Compute, publish and store the drift report for ``event["current_day"]``."""
    config = load_config(DriftConfig, CONFIG_DIR / "monitoring.yaml")
    dataset = str(event.get("dataset", config.dataset))
    reference_day = str(event.get("reference_day", config.reference_day))
    current_day = str(event["current_day"])
    bucket = os.environ["DATA_BUCKET"]
    work_dir.mkdir(parents=True, exist_ok=True)
    columns = {
        day: scored_columns(*_download(s3, bucket, dataset, day, work_dir), config.features)
        for day in (reference_day, current_day)
    }
    report = drift_report(columns[reference_day], columns[current_day], config)
    report = {
        "dataset": dataset,
        "reference_day": reference_day,
        "current_day": current_day,
        "report_only": list(config.report_only),
        **report,
    }
    cloudwatch.put_metric_data(Namespace=NAMESPACE, MetricData=cloudwatch_metrics(report, dataset))
    s3.put_object(
        Bucket=bucket,
        Key=f"monitoring/drift/{dataset}/{current_day}.json",
        Body=json.dumps(report).encode("utf-8"),
        ContentType="application/json",
    )
    return report


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:  # pragma: no cover
    """Lambda entry point."""
    import boto3  # noqa: PLC0415

    return drift_step(event, boto3.client("s3"), boto3.client("cloudwatch"))
