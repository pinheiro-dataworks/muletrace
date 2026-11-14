import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from muletrace.models.artifact import load_artifact, save_artifact
from muletrace.models.calibration import IsotonicCalibrator, brier_score, reliability_table
from muletrace.models.train import fit
from tests.fixtures.model_data import FEATURES, TRAINING, labelled_frame


@pytest.fixture(scope="module")
def data() -> tuple[pl.DataFrame, pl.DataFrame]:
    return labelled_frame(4000, 1), labelled_frame(2000, 2)


def test_isotonic_calibration_round_trip() -> None:
    rng = np.random.default_rng(0)
    scores = rng.random(2000)
    labels = rng.random(2000) < scores
    calibrator = IsotonicCalibrator.fit(scores, labels)
    probabilities = calibrator.transform(scores)
    assert np.all(np.diff(calibrator.y) >= 0)
    assert brier_score(probabilities, labels) <= brier_score(scores, labels) + 1e-9
    restored = IsotonicCalibrator.from_dict(json.loads(json.dumps(calibrator.to_dict())))
    assert np.allclose(restored.transform(scores), probabilities)
    table = reliability_table(probabilities, labels, n_bins=5)
    assert sum(row["accounts"] for row in table) == 2000


def test_reliability_table_skips_empty_bins() -> None:
    table = reliability_table(np.array([0.1, 0.2, 0.9]), np.array([False, False, True]), n_bins=10)
    assert [row["accounts"] for row in table] == [1, 1, 1]


def test_artifact_round_trip(data, tmp_path: Path) -> None:
    train, valid = data
    model = fit(train, valid, FEATURES, {"num_leaves": 4}, TRAINING)
    calibrator = IsotonicCalibrator.fit(model.predict(valid), valid["label"].to_numpy())
    save_artifact(tmp_path, model.booster, calibrator, {"features": list(model.features)})
    artifact = load_artifact(tmp_path)
    raw, probability = artifact.score_frame(valid)
    assert np.allclose(raw, model.predict(valid))
    assert np.allclose(probability, calibrator.transform(raw))
    assert artifact.features == model.features
