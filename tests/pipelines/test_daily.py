import json
import shutil
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from muletrace.config import CONFIG_DIR, load_config
from muletrace.data.labels import LabelConfig
from muletrace.features.build import build_snapshots
from muletrace.features.config import FeatureConfig
from muletrace.models.artifact import load_artifact
from muletrace.pipelines import daily, train_entry
from muletrace.pipelines.step_functions import daily_scoring_definition
from muletrace.serving.feature_client import InMemoryFeatureStore
from muletrace.serving.handler import ScoringService
from muletrace.serving.replay_consumer import process_batch

TIMES = [datetime(2022, 9, d) for d in range(2, 10)]


class FakeS3:
    """Maps S3 keys to files in a temporary folder."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        shutil.copy(self.root / bucket / key, filename)

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        target = self.root / bucket / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(filename, target)


def test_step_functions_definition_is_wired_end_to_end() -> None:
    definition = daily_scoring_definition("arn:build", "arn:score", "arn:topic")
    states = definition["States"]
    assert definition["StartAt"] == "BuildSnapshot"
    assert states["BuildSnapshot"]["Next"] == "ScoreAndPublish"
    assert states["ScoreAndPublish"]["End"] is True
    for name in ("BuildSnapshot", "ScoreAndPublish"):
        assert states[name]["Catch"][0]["Next"] == "NotifyFailure"
        assert states[name]["Retry"][0]["MaxAttempts"] == 3
    assert states["NotifyFailure"]["Next"] == "Failed"
    json.dumps(definition)  # serialisable for the CDK stack


def test_daily_workflow_end_to_end(
    world: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    labels = load_config(LabelConfig, CONFIG_DIR / "labels.yaml")
    features = load_config(FeatureConfig, CONFIG_DIR / "features.yaml")
    snapshots = build_snapshots(
        world / "bucket" / "data" / "processed" / "HI-Small",
        tmp_path / "cache",
        TIMES,
        labels,
        features,
    )
    snapshot_dir = tmp_path / "channel"
    snapshot_dir.mkdir()
    for as_of, frame in snapshots.group_by("as_of"):
        frame.write_parquet(snapshot_dir / f"{as_of[0]:%Y-%m-%d}.parquet")
    metadata = train_entry.run(
        snapshot_dir, tmp_path / "model", {"num_leaves": 4, "min_data_in_leaf": 20}, CONFIG_DIR
    )
    assert metadata["labels_known_by"] == "2022-09-09T00:00:00"
    assert metadata["validated_on_snapshot"] == "2022-09-07T00:00:00"

    monkeypatch.setenv("DATA_BUCKET", "data")
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.delenv("MODEL_URI", raising=False)
    s3 = FakeS3(world / "bucket")
    event = {"dataset": "HI-Small", "as_of": "2022-09-09"}
    built = daily.build_snapshot_step(event, s3=s3, work_dir=tmp_path / "work")
    assert built["snapshot_key"] == "snapshots/HI-Small/2022-09-09.parquet"
    store = InMemoryFeatureStore()
    published = daily.score_and_publish_step(event, s3=s3, store=store, work_dir=tmp_path / "work2")
    assert published["feature_items"] == built["accounts"] == len(store.items)
    scores = pl.read_parquet(world / "bucket" / "data" / published["scores_key"])
    assert scores["probability"].is_between(0, 1).all()

    service = ScoringService(
        load_artifact(tmp_path / "model"), store, "HI-Small", probability_cap=0.99
    )
    first = scores["account_id"][0]
    record = {
        "messageId": "1",
        "body": json.dumps(
            {"tx_id": 1, "receiver_id": int(first), "timestamp": "2022-09-09T10:00:00"}
        ),
    }
    broken = {"messageId": "2", "body": "{not json"}
    report = process_batch({"Records": [record, broken]}, service, threshold=0.0)
    assert report == {"batchItemFailures": [{"itemIdentifier": "2"}], "alerts": 1}
    assert process_batch({"Records": [record]}, service, threshold=1.1)["alerts"] == 0
