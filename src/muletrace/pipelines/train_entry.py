"""Entry point of the SageMaker training container.

SageMaker mounts the ``snapshots`` channel (Parquet feature snapshots) and passes the
hyper-parameters as JSON; the model artefact written to ``SM_MODEL_DIR`` is packaged by
SageMaker into ``model.tar.gz``. The same :func:`train_final_model` runs locally through
``muletrace models train-final``, so the cloud job is not a second implementation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import polars as pl

from muletrace.config import CONFIG_DIR, load_config
from muletrace.data.labels import LabelConfig
from muletrace.features.config import FeatureConfig
from muletrace.models.artifact import save_artifact
from muletrace.models.final import train_final_model
from muletrace.models.train import TrainingConfig

_INTEGER_PARAMS = ("num_leaves", "min_data_in_leaf")


def parse_hyperparameters(raw: dict[str, str]) -> dict[str, Any]:
    """SageMaker passes every hyper-parameter as a string; restore the integers."""
    return {key: int(value) if key in _INTEGER_PARAMS else value for key, value in raw.items()}


def run(
    snapshot_dir: Path, model_dir: Path, hyperparameters: dict[str, Any], config_dir: Path
) -> dict[str, Any]:
    """Train on every snapshot file in ``snapshot_dir`` and write the artefact to ``model_dir``."""
    snapshots = pl.concat(
        [pl.read_parquet(path) for path in sorted(snapshot_dir.glob("*.parquet"))]
    )
    labels = load_config(LabelConfig, config_dir / "labels.yaml")
    model, calibrator, metadata = train_final_model(
        snapshots,
        load_config(FeatureConfig, config_dir / "features.yaml"),
        load_config(TrainingConfig, config_dir / "training.yaml"),
        hyperparameters,
        labels.horizon,
    )
    save_artifact(model_dir, model.booster, calibrator, metadata)
    return metadata


def main() -> None:  # pragma: no cover - exercised inside the SageMaker container
    """Read SageMaker's environment and train."""
    hyperparameters = parse_hyperparameters(json.loads(os.environ.get("SM_HPS", "{}")))
    metadata = run(
        Path(os.environ["SM_CHANNEL_SNAPSHOTS"]),
        Path(os.environ["SM_MODEL_DIR"]),
        hyperparameters,
        Path(os.environ.get("MULETRACE_CONFIG_DIR", str(CONFIG_DIR))),
    )
    print(json.dumps({"valid_average_precision": metadata["valid_average_precision"]}))


if __name__ == "__main__":  # pragma: no cover
    main()
