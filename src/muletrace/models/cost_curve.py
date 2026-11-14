"""Expected cost of an alert policy, in review units.

A false positive costs one analyst review (C_FP = 1). A missed mule costs ``missed_cost`` review
units, an assumption swept over several values (A2 in the business case). Two policies are
compared:

* **budget policy** — alert on the top ``k`` accounts, for every ``k`` up to a maximum;
* **threshold policy** — alert when the calibrated probability exceeds ``1 / (1 + missed_cost)``,
  the cost-minimising rule when probabilities are calibrated.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from muletrace.models.evaluate import rank_order

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


def cost_by_budget(
    labels: BoolArray, scores: FloatArray, missed_cost: float, max_alerts: int
) -> FloatArray:
    """Expected cost when alerting on the top ``k`` accounts, for ``k = 0 … max_alerts``."""
    ranked = labels[rank_order(scores)][:max_alerts]
    true_positives = np.concatenate([[0], np.cumsum(ranked)])
    alerts = np.arange(true_positives.size)
    false_positives = alerts - true_positives
    missed = labels.sum() - true_positives
    return np.asarray(false_positives + missed_cost * missed, dtype=np.float64)


def threshold_policy_cost(
    labels: BoolArray, probabilities: FloatArray, missed_cost: float
) -> tuple[float, int]:
    """Cost and alert count of the decision-theoretic threshold on calibrated probabilities."""
    alerted = probabilities > 1.0 / (1.0 + missed_cost)
    false_positives = int(np.sum(alerted & ~labels))
    missed = int(np.sum(~alerted & labels))
    return float(false_positives + missed_cost * missed), int(alerted.sum())


def cost_summary(
    *,
    labels: BoolArray,
    scores: FloatArray,
    probabilities: FloatArray | None,
    missed_cost: float,
    budget_alerts: int,
    max_alerts: int,
) -> dict[str, float]:
    """Cost at the analyst budget, the best achievable budget, and the threshold policy."""
    curve = cost_by_budget(labels, scores, missed_cost, max_alerts)
    best = int(np.argmin(curve))
    summary = {
        "missed_mule_cost": missed_cost,
        "cost_with_no_alerts": float(curve[0]),
        "cost_at_budget": float(curve[min(budget_alerts, curve.size - 1)]),
        "best_alerts": best,
        "best_cost": float(curve[best]),
    }
    if probabilities is not None:
        cost, alerts = threshold_policy_cost(labels, probabilities, missed_cost)
        summary |= {"threshold_policy_cost": cost, "threshold_policy_alerts": alerts}
    return summary
