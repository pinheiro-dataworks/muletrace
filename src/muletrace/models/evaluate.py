"""Decision metrics: what happens when the analyst team works the top of the queue.

All metrics are computed for a fixed **alert budget** expressed in alerts per 10,000 scored
accounts. Ranking is deterministic: higher score first, then higher tie-breaker, then the
original row order. Deterministic ties matter for rules, whose scores are small integers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from numpy.typing import NDArray
from pydantic import Field
from sklearn.metrics import average_precision_score

from muletrace.config import StrictModel

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


def alert_count(n_scored: int, alerts_per_10k: float) -> int:
    """Number of alerts the team can work for a population of ``n_scored`` accounts."""
    if n_scored <= 0:
        return 0
    return max(1, math.floor(n_scored * alerts_per_10k / 10_000))


def rank_order(scores: FloatArray, tie_breaker: FloatArray | None = None) -> NDArray[np.intp]:
    """Indices from highest to lowest score; ties by higher ``tie_breaker``, then row order."""
    index = np.arange(scores.size)
    keys: tuple[NDArray[np.generic], ...] = (index, -np.nan_to_num(scores, nan=-np.inf))
    if tie_breaker is not None:
        keys = (index, -np.nan_to_num(tie_breaker, nan=-np.inf), keys[1])
    return np.lexsort(keys)


def top_k_mask(scores: FloatArray, k: int, tie_breaker: FloatArray | None = None) -> BoolArray:
    """Boolean mask of the ``k`` accounts the team would review."""
    mask = np.zeros(scores.size, dtype=bool)
    mask[rank_order(scores, tie_breaker)[:k]] = True
    return mask


@dataclass(frozen=True)
class BudgetResult:
    """Outcome of working the top ``alerts`` accounts of one snapshot."""

    alerts_per_10k: float
    alerts: int
    true_positives: int
    positives: int
    value_detected: float
    value_total: float

    @property
    def recall(self) -> float:
        """Share of the mules in the horizon that were alerted."""
        return self.true_positives / self.positives if self.positives else 0.0

    @property
    def precision(self) -> float:
        """Share of alerts that were mules (precision at k)."""
        return self.true_positives / self.alerts if self.alerts else 0.0

    @property
    def value_share(self) -> float:
        """Share of the simulated illicit inflow that reached alerted accounts."""
        return self.value_detected / self.value_total if self.value_total else 0.0


def evaluate_budget(
    labels: BoolArray,
    scores: FloatArray,
    values: FloatArray,
    alerts_per_10k: float,
    tie_breaker: FloatArray | None = None,
) -> BudgetResult:
    """Work the top of the queue for one snapshot and count what was caught."""
    k = alert_count(labels.size, alerts_per_10k)
    alerted = top_k_mask(scores, k, tie_breaker)
    return BudgetResult(
        alerts_per_10k=alerts_per_10k,
        alerts=k,
        true_positives=int(np.sum(labels & alerted)),
        positives=int(np.sum(labels)),
        value_detected=float(np.sum(values[alerted])),
        value_total=float(np.sum(values)),
    )


def average_precision(labels: BoolArray, scores: FloatArray) -> float:
    """Area under the precision-recall curve (PR-AUC as average precision)."""
    if not labels.any():
        return float("nan")
    return float(average_precision_score(labels, np.nan_to_num(scores, nan=-np.inf)))


class BootstrapConfig(StrictModel):
    """Bootstrap resampling for confidence intervals."""

    replicates: int = Field(gt=0)
    seed: int


class EvaluationConfig(StrictModel):
    """Evaluation design, read from ``configs/evaluation.yaml``."""

    first_snapshot: datetime
    last_snapshot: datetime
    snapshot_step_hours: int = Field(gt=0)
    test_snapshots: tuple[datetime, ...] = Field(min_length=1)
    headline_alert_budget_per_10k: float = Field(gt=0)
    alert_budgets_per_10k: tuple[float, ...] = Field(min_length=1)
    missed_mule_cost_review_units: tuple[float, ...] = Field(min_length=1)
    bootstrap: BootstrapConfig

    @property
    def snapshot_step(self) -> timedelta:
        """Time between consecutive snapshots."""
        return timedelta(hours=self.snapshot_step_hours)


def budget_table(
    labels: BoolArray,
    scores: FloatArray,
    values: FloatArray,
    budgets: tuple[float, ...],
    tie_breaker: FloatArray | None = None,
) -> list[dict[str, float]]:
    """Recall, precision and value share at every budget, as plain dictionaries."""
    rows = []
    for budget in budgets:
        result = evaluate_budget(labels, scores, values, budget, tie_breaker)
        rows.append(
            {
                "alerts_per_10k": budget,
                "alerts": result.alerts,
                "true_positives": result.true_positives,
                "positives": result.positives,
                "recall": round(result.recall, 4),
                "precision": round(result.precision, 4),
                "value_share": round(result.value_share, 4),
            }
        )
    return rows
