import numpy as np
import pytest

from muletrace.models.bootstrap import BootstrapSnapshot, bootstrap_metrics, interval
from muletrace.models.cost_curve import cost_by_budget, cost_summary, threshold_policy_cost
from muletrace.models.evaluate import average_precision


def test_cost_curve_and_threshold_policy() -> None:
    labels = np.array([True, False, True, False, False])
    scores = np.array([0.9, 0.8, 0.7, 0.2, 0.1])
    curve = cost_by_budget(labels, scores, missed_cost=10, max_alerts=5)
    assert curve.tolist() == [20, 10, 11, 1, 2, 3]
    # The threshold is 1 / 11: every account is above it, so three false positives.
    assert threshold_policy_cost(labels, scores, missed_cost=10) == (3.0, 5)
    assert threshold_policy_cost(labels, scores, missed_cost=1) == (1.0, 3)
    summary = cost_summary(
        labels=labels,
        scores=scores,
        probabilities=None,
        missed_cost=10,
        budget_alerts=2,
        max_alerts=5,
    )
    assert summary["best_alerts"] == 3
    assert summary["cost_at_budget"] == 11
    assert "threshold_policy_cost" not in summary


def test_bootstrap_point_estimate_matches_direct_metrics() -> None:
    rng = np.random.default_rng(5)
    labels = rng.random(20_000) < 0.01
    good = labels + rng.normal(0, 0.5, labels.size)
    random = rng.random(labels.size)
    snapshot = BootstrapSnapshot.from_scores(labels, [good, random])
    point = bootstrap_metrics([snapshot], 100, replicates=1, seed=0, poisson=False)
    assert point["average_precision"][0, 0] == pytest.approx(
        average_precision(labels, good), abs=1e-9
    )
    samples = bootstrap_metrics([snapshot], 100, replicates=200, seed=1)
    low, high = interval(samples["recall"][0] - samples["recall"][1])
    assert low > 0  # the informative model beats random with confidence
    assert low <= high
