"""Probability calibration and its diagnostics.

The model's raw scores rank well but are not probabilities an analyst can read. An isotonic map,
fitted on the validation snapshot of each fold, turns them into calibrated probabilities. The
map is stored as two arrays and applied with :func:`numpy.interp`, so the serving Lambda needs no
scikit-learn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class IsotonicCalibrator:
    """Monotone piecewise-linear map from raw score to probability."""

    x: FloatArray
    y: FloatArray

    @classmethod
    def fit(cls, scores: FloatArray, labels: NDArray[np.bool_]) -> IsotonicCalibrator:
        """Fit on held-out scores and labels.

        scikit-learn is imported here, not at module level, so that applying a fitted map (the
        serving path) needs only NumPy.
        """
        from sklearn.isotonic import IsotonicRegression  # noqa: PLC0415

        model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        model.fit(scores, labels.astype(np.float64))
        return cls(np.asarray(model.X_thresholds_, float), np.asarray(model.y_thresholds_, float))

    def transform(self, scores: FloatArray) -> FloatArray:
        """Calibrated probabilities; scores outside the fitted range are clipped."""
        return np.asarray(np.interp(scores, self.x, self.y), dtype=np.float64)

    def to_dict(self) -> dict[str, list[float]]:
        """JSON-friendly form for the model artefact."""
        return {"x": self.x.tolist(), "y": self.y.tolist()}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> IsotonicCalibrator:
        """Inverse of :meth:`to_dict`."""
        return cls(np.asarray(payload["x"], float), np.asarray(payload["y"], float))


def brier_score(probabilities: FloatArray, labels: NDArray[np.bool_]) -> float:
    """Mean squared error of the probabilities."""
    return float(np.mean((probabilities - labels.astype(np.float64)) ** 2))


def reliability_table(
    probabilities: FloatArray, labels: NDArray[np.bool_], n_bins: int = 10
) -> list[dict[str, float]]:
    """Observed positive rate against mean predicted probability, by quantile bin.

    Quantile bins (rather than fixed-width bins) keep every bin populated when almost all
    probabilities are tiny, which is the normal case here.
    """
    order = np.argsort(probabilities, kind="stable")
    rows = []
    for chunk in np.array_split(order, n_bins):
        if chunk.size == 0:
            continue
        rows.append(
            {
                "accounts": int(chunk.size),
                "mean_predicted": round(float(probabilities[chunk].mean()), 6),
                "observed_rate": round(float(labels[chunk].mean()), 6),
            }
        )
    return rows
