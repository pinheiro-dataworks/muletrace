"""Shared fixtures: a small trained artefact, a snapshot and a scoring service."""

from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from muletrace.models.artifact import load_artifact, save_artifact
from muletrace.models.calibration import IsotonicCalibrator
from muletrace.models.train import fit
from muletrace.serving.batch import feature_items
from muletrace.serving.feature_client import InMemoryFeatureStore
from muletrace.serving.handler import ScoringService
from tests.fixtures.model_data import TRAINING, labelled_frame

AS_OF = datetime(2022, 9, 9)
FEATURES = ("signal", "noise", "entity_type", "sparse")


@pytest.fixture(scope="module")
def artifact_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    def with_sparse(frame: pl.DataFrame) -> pl.DataFrame:
        # A column with missing values exercises the NaN path of the encoding.
        return frame.with_columns(
            sparse=pl.when(pl.col("noise") > 0).then(pl.col("noise") * 3.14159)
        )

    train, valid = with_sparse(labelled_frame(4000, 1)), with_sparse(labelled_frame(2000, 2))
    model = fit(train, valid, list(FEATURES), {"num_leaves": 4}, TRAINING)
    calibrator = IsotonicCalibrator.fit(model.predict(valid), valid["label"].to_numpy())
    folder = tmp_path_factory.mktemp("model")
    save_artifact(
        folder,
        model.booster,
        calibrator,
        {"features": list(FEATURES), "model": "test", "trained_on_snapshots": ["2022-09-06"]},
    )
    return folder


@pytest.fixture(scope="module")
def snapshot() -> pl.DataFrame:
    frame = labelled_frame(500, 3)
    return frame.with_columns(
        account_id=pl.int_range(pl.len()).cast(pl.UInt32),
        as_of=pl.lit(AS_OF),
        sparse=pl.when(pl.col("noise") > 0).then(pl.col("noise") * 3.14159),
    )


@pytest.fixture
def service(artifact_dir: Path, snapshot: pl.DataFrame) -> ScoringService:
    artifact = load_artifact(artifact_dir)
    store = InMemoryFeatureStore()
    store.put_many(feature_items(snapshot, artifact.features, "HI-Small"))
    return ScoringService(artifact=artifact, store=store, dataset="HI-Small", probability_cap=0.99)
