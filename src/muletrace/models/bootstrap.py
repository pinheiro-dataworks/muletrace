"""Paired Poisson bootstrap for decision metrics.

Each replicate draws a Poisson(1) weight per account, the standard large-sample bootstrap that
avoids materialising resampled tables. The same weights are applied to every model in a
replicate, so the interval of a *difference* between two models accounts for their correlation
(paired bootstrap). Snapshots are resampled independently and the metric is pooled over them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from muletrace.models.evaluate import rank_order

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
_BUDGET_UNIT = 10_000


@dataclass(frozen=True)
class BootstrapSnapshot:
    """Labels of one snapshot and the rank order each model gives it."""

    labels: BoolArray
    orders: tuple[NDArray[np.intp], ...]

    @classmethod
    def from_scores(
        cls,
        labels: BoolArray,
        scores: Sequence[FloatArray],
        tie_breakers: Sequence[FloatArray | None] | None = None,
    ) -> BootstrapSnapshot:
        """Rank the snapshot once per model, exactly as the point estimates do."""
        ties = tie_breakers if tie_breakers is not None else [None] * len(scores)
        return cls(labels, tuple(rank_order(s, t) for s, t in zip(scores, ties, strict=True)))


def _recall_terms(
    labels: BoolArray, weights: FloatArray, alerts_per_10k: float
) -> tuple[float, float]:
    """Weighted hits and positives for one ranked snapshot (inputs in rank order)."""
    budget = max(weights.sum() * alerts_per_10k / _BUDGET_UNIT, 1.0)
    alerted = np.cumsum(weights) <= budget
    return float(np.sum(weights * labels * alerted)), float(np.sum(weights * labels))


def _average_precision_terms(labels: BoolArray, weights: FloatArray) -> tuple[float, float]:
    """Weighted sum of precision at each positive, and the weighted number of positives."""
    cumulative = np.cumsum(weights)
    cumulative_hits = np.cumsum(weights * labels)
    at_positive = labels & (weights > 0)
    precision = cumulative_hits[at_positive] / cumulative[at_positive]
    return float(np.sum(weights[at_positive] * precision)), float(np.sum(weights * labels))


def bootstrap_metrics(
    snapshots: Sequence[BootstrapSnapshot],
    alerts_per_10k: float,
    replicates: int,
    seed: int,
    *,
    poisson: bool = True,
) -> dict[str, FloatArray]:
    """Pooled recall at the budget and average precision, per model and replicate.

    With ``poisson=False`` every weight is one, which gives the point estimate through exactly
    the same code path as the replicates. Returns arrays of shape ``(models, replicates)`` under
    the keys ``recall`` and ``average_precision``.
    """
    n_models = len(snapshots[0].orders)
    rng = np.random.default_rng(seed)
    recall = np.zeros((n_models, replicates))
    precision = np.zeros((n_models, replicates))
    for replicate in range(replicates):
        totals = np.zeros((4, n_models))
        for snapshot in snapshots:
            weights = (
                rng.poisson(1.0, size=snapshot.labels.size).astype(np.float64)
                if poisson
                else np.ones(snapshot.labels.size)
            )
            for model, order in enumerate(snapshot.orders):
                labels, ordered = snapshot.labels[order], weights[order]
                totals[0:2, model] += _recall_terms(labels, ordered, alerts_per_10k)
                totals[2:4, model] += _average_precision_terms(labels, ordered)
        recall[:, replicate] = np.divide(
            totals[0], totals[1], out=np.zeros(n_models), where=totals[1] > 0
        )
        precision[:, replicate] = np.divide(
            totals[2], totals[3], out=np.zeros(n_models), where=totals[3] > 0
        )
    return {"recall": recall, "average_precision": precision}


def interval(samples: FloatArray, level: float = 0.95) -> tuple[float, float]:
    """Percentile interval of bootstrap samples."""
    tail = (1 - level) / 2 * 100
    low, high = np.percentile(samples, [tail, 100 - tail])
    return round(float(low), 4), round(float(high), 4)
