"""Reason codes from SHAP values.

LightGBM computes exact TreeSHAP contributions natively (``pred_contrib=True``), so no extra
dependency is needed. Contributions are in log-odds; positive values push the risk up. A reason
code is a feature with one of the largest positive contributions for an account, reported with
the account's value for that feature so an analyst can check it.
"""

from __future__ import annotations

from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from numpy.typing import NDArray

from muletrace.models.train import FittedModel


def booster_contributions(
    booster: lgb.Booster,
    features: tuple[str, ...],
    frame: pl.DataFrame,
    num_iteration: int | None = None,
) -> NDArray[np.float64]:
    """SHAP contributions of any booster, shape ``(rows, features)``; bias column dropped."""
    matrix = frame.select(features).to_numpy().astype(np.float64)
    raw = booster.predict(matrix, num_iteration=num_iteration, pred_contrib=True)
    return np.asarray(raw, dtype=np.float64)[:, :-1]


def contributions(model: FittedModel, frame: pl.DataFrame) -> NDArray[np.float64]:
    """SHAP contributions of a fitted model at its best iteration."""
    return booster_contributions(model.booster, model.features, frame, model.best_iteration)


def global_importance(
    contrib: NDArray[np.float64], features: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Mean absolute contribution per feature, largest first."""
    mean_abs = np.abs(contrib).mean(axis=0)
    order = np.argsort(-mean_abs, kind="stable")
    return [
        {"feature": features[i], "mean_abs_contribution": round(float(mean_abs[i]), 5)}
        for i in order
    ]


def reason_codes(
    contrib: NDArray[np.float64], frame: pl.DataFrame, features: tuple[str, ...], top: int = 3
) -> list[list[dict[str, Any]]]:
    """For each row, the ``top`` features that push its risk up the most."""
    values = frame.select(features).to_numpy()
    codes = []
    for row, row_contrib in enumerate(contrib):
        order = np.argsort(-row_contrib, kind="stable")[:top]
        codes.append(
            [
                {
                    "feature": features[i],
                    "contribution": round(float(row_contrib[i]), 4),
                    "value": None if values[row, i] is None else float(values[row, i]),
                }
                for i in order
                if row_contrib[i] > 0
            ]
        )
    return codes
