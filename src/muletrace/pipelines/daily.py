"""The two Lambda steps of the daily scoring workflow.

S3 layout (``DATA_BUCKET``)::

    processed/<dataset>/transactions.parquet, accounts.parquet   inputs, uploaded once
    snapshots/<dataset>/<YYYY-MM-DD>.parquet                     written by BuildSnapshot
    scores/<dataset>/<YYYY-MM-DD>.parquet                        written by ScoreAndPublish

Both handlers take ``{"dataset": "...", "as_of": "YYYY-MM-DD"}``. Their AWS clients and the
feature store are injectable so the logic is tested locally with fakes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from muletrace.config import CONFIG_DIR, load_config
from muletrace.data.labels import LabelConfig
from muletrace.features.build import build_snapshots
from muletrace.features.config import FeatureConfig
from muletrace.models.artifact import load_artifact
from muletrace.serving.batch import feature_items, score_snapshot
from muletrace.serving.feature_client import DynamoDBFeatureStore, FeatureStore
from muletrace.serving.model_source import resolve_model_dir

WORK_DIR = Path("/tmp/muletrace-daily")  # noqa: S108  # nosec B108


@dataclass(frozen=True)
class DailyRequest:
    """Validated input of a workflow execution."""

    dataset: str
    as_of: datetime

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> DailyRequest:
        """Parse ``{"dataset": ..., "as_of": "YYYY-MM-DD"}``."""
        return cls(str(event["dataset"]), datetime.fromisoformat(str(event["as_of"])))

    @property
    def day(self) -> str:
        """The as-of date as ``YYYY-MM-DD``."""
        return self.as_of.date().isoformat()


def _s3(client: Any | None) -> Any:  # noqa: ANN401 - boto3 client
    if client is not None:
        return client
    import boto3  # noqa: PLC0415

    return boto3.client("s3")


def build_snapshot_step(
    event: dict[str, Any],
    s3: Any | None = None,  # noqa: ANN401 - boto3 client
    work_dir: Path = WORK_DIR,
) -> dict[str, Any]:
    """Build the as-of snapshot from the processed tables and upload it."""
    request = DailyRequest.from_event(event)
    client, bucket = _s3(s3), os.environ["DATA_BUCKET"]
    dataset_dir = work_dir / "processed" / request.dataset
    dataset_dir.mkdir(parents=True, exist_ok=True)
    for name in ("transactions.parquet", "accounts.parquet"):
        client.download_file(bucket, f"processed/{request.dataset}/{name}", str(dataset_dir / name))
    snapshot = build_snapshots(
        dataset_dir,
        work_dir / "cache",
        [request.as_of],
        load_config(LabelConfig, CONFIG_DIR / "labels.yaml"),
        load_config(FeatureConfig, CONFIG_DIR / "features.yaml"),
    )
    local = work_dir / f"{request.day}.parquet"
    snapshot.write_parquet(local, compression="zstd")
    key = f"snapshots/{request.dataset}/{request.day}.parquet"
    client.upload_file(str(local), bucket, key)
    return {"snapshot_key": key, "accounts": snapshot.height}


def score_and_publish_step(
    event: dict[str, Any],
    s3: Any | None = None,  # noqa: ANN401
    store: FeatureStore | None = None,
    work_dir: Path = WORK_DIR,
) -> dict[str, Any]:
    """Write feature vectors to the online store and scores to S3."""
    request = DailyRequest.from_event(event)
    client, bucket = _s3(s3), os.environ["DATA_BUCKET"]
    work_dir.mkdir(parents=True, exist_ok=True)
    local = work_dir / f"{request.day}.parquet"
    client.download_file(bucket, f"snapshots/{request.dataset}/{request.day}.parquet", str(local))
    snapshot = pl.read_parquet(local)
    artifact = load_artifact(resolve_model_dir())
    target = store if store is not None else DynamoDBFeatureStore(os.environ["FEATURE_TABLE"])
    written = target.put_many(feature_items(snapshot, artifact.features, request.dataset))
    scores = score_snapshot(snapshot, artifact)
    scores_path = work_dir / f"scores-{request.day}.parquet"
    scores.write_parquet(scores_path, compression="zstd")
    key = f"scores/{request.dataset}/{request.day}.parquet"
    client.upload_file(str(scores_path), bucket, key)
    return {"feature_items": written, "scores_key": key}


def build_snapshot_handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    """Lambda entry point of ``BuildSnapshot``."""
    return build_snapshot_step(event)  # pragma: no cover - thin AWS wrapper


def score_and_publish_handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    """Lambda entry point of ``ScoreAndPublish``."""
    return score_and_publish_step(event)  # pragma: no cover - thin AWS wrapper
