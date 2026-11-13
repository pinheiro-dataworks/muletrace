"""Save and load the model artefact used by the batch scorer and the serving Lambda.

An artefact is a folder with three files:

* ``model.txt`` — the LightGBM booster in its native text format;
* ``calibrator.json`` — the isotonic map from raw score to probability;
* ``metadata.json`` — feature order, parameters, training window and provenance.

Loading needs only LightGBM and NumPy, which keeps the Lambda image small.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import lightgbm as lgb
import numpy as np
from numpy.typing import NDArray

from muletrace.models.calibration import IsotonicCalibrator

if TYPE_CHECKING:  # Polars is a batch dependency; the Lambda image does not ship it.
    import polars as pl

MODEL_FILE = "model.txt"
CALIBRATOR_FILE = "calibrator.json"
METADATA_FILE = "metadata.json"


@dataclass(frozen=True)
class ModelArtifact:
    """A booster, its calibrator and the feature order they expect."""

    booster: lgb.Booster
    calibrator: IsotonicCalibrator
    metadata: dict[str, Any]

    @property
    def features(self) -> tuple[str, ...]:
        """Feature names in the order the booster was trained on."""
        return tuple(self.metadata["features"])

    def score_matrix(
        self, matrix: NDArray[np.float64]
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Raw score and calibrated probability for a feature matrix in :attr:`features` order."""
        raw = np.asarray(self.booster.predict(matrix), dtype=np.float64)
        return raw, self.calibrator.transform(raw)

    def contributions_matrix(self, matrix: NDArray[np.float64]) -> NDArray[np.float64]:
        """SHAP contributions per feature (bias column dropped) for a feature matrix."""
        raw = self.booster.predict(matrix, pred_contrib=True)
        return np.asarray(raw, dtype=np.float64)[:, :-1]

    def score_frame(self, frame: pl.DataFrame) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Raw score and calibrated probability for every row of ``frame``."""
        return self.score_matrix(frame.select(self.features).to_numpy().astype(np.float64))


def save_artifact(
    folder: Path, booster: lgb.Booster, calibrator: IsotonicCalibrator, metadata: dict[str, Any]
) -> None:
    """Write the three artefact files; the booster keeps only its best iteration."""
    folder.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(folder / MODEL_FILE), num_iteration=booster.best_iteration or None)
    (folder / CALIBRATOR_FILE).write_text(
        json.dumps(calibrator.to_dict()), encoding="utf-8", newline="\n"
    )
    (folder / METADATA_FILE).write_text(
        json.dumps(metadata, indent=2, default=str), encoding="utf-8", newline="\n"
    )


def load_artifact(folder: Path) -> ModelArtifact:
    """Read an artefact written by :func:`save_artifact`."""
    return ModelArtifact(
        booster=lgb.Booster(model_file=str(folder / MODEL_FILE)),
        calibrator=IsotonicCalibrator.from_dict(
            json.loads((folder / CALIBRATOR_FILE).read_text(encoding="utf-8"))
        ),
        metadata=json.loads((folder / METADATA_FILE).read_text(encoding="utf-8")),
    )
