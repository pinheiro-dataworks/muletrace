"""Train the production model: the last fold of the backtest, on all labels known today.

The final model is trained exactly like the backtest's last fold, so the evaluation describes the
model that is deployed: validation is the snapshot one horizon before the latest one (its labels
are complete), training is every earlier snapshot, and labels are truncated at the latest
snapshot time. Hyper-parameters are the ones the backtest chose.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import polars as pl

from muletrace.features.build import model_features
from muletrace.features.config import FeatureConfig
from muletrace.models.backtest import make_folds, with_known_labels
from muletrace.models.calibration import IsotonicCalibrator
from muletrace.models.evaluate import average_precision
from muletrace.models.train import FittedModel, TrainingConfig, fit


def train_final_model(
    snapshots: pl.DataFrame,
    features: FeatureConfig,
    training: TrainingConfig,
    params: dict[str, Any],
    horizon: timedelta,
) -> tuple[FittedModel, IsotonicCalibrator, dict[str, Any]]:
    """Fit, calibrate and describe the model on every snapshot in ``snapshots``."""
    times = sorted(snapshots["as_of"].unique().to_list())
    fold = make_folds(times, (times[-1],), horizon)[0]
    known = with_known_labels(snapshots, fold.test_at)
    train = known.filter(pl.col("as_of").is_in(fold.train_at))
    valid = known.filter(pl.col("as_of") == fold.valid_at)
    names = model_features(features, include_graph=True)
    model = fit(train, valid, names, params, training)
    valid_scores = model.predict(valid)
    calibrator = IsotonicCalibrator.fit(valid_scores, valid["label"].to_numpy())
    metadata = {
        "model": "lgbm_tabular_graph",
        "features": list(model.features),
        "params": model.params,
        "trees": model.best_iteration,
        "trained_on_snapshots": [t.isoformat() for t in fold.train_at],
        "validated_on_snapshot": fold.valid_at.isoformat(),
        "labels_known_by": fold.test_at.isoformat(),
        "valid_average_precision": round(
            average_precision(valid["label"].to_numpy(), valid_scores), 5
        ),
        "train_rows": train.height,
        "train_positives": int(train["label"].sum()),
    }
    return model, calibrator, metadata
