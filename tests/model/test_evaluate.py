import math
from datetime import timedelta

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from muletrace.config import CONFIG_DIR, load_config
from muletrace.models.evaluate import (
    EvaluationConfig,
    alert_count,
    average_precision,
    budget_table,
    evaluate_budget,
    rank_order,
    top_k_mask,
)


@pytest.mark.parametrize(
    ("n", "budget", "expected"),
    [(0, 20, 0), (100, 20, 1), (10_000, 20, 20), (276_396, 20, 552), (49_999, 5, 24)],
)
def test_alert_count(n: int, budget: float, expected: int) -> None:
    assert alert_count(n, budget) == expected


def test_ties_are_broken_by_tie_breaker_then_row_order() -> None:
    scores = np.array([1.0, 2.0, 2.0, 2.0, np.nan])
    tie = np.array([0.0, 5.0, 9.0, 5.0, 100.0])
    assert rank_order(scores, tie).tolist() == [2, 1, 3, 0, 4]
    assert rank_order(scores).tolist() == [1, 2, 3, 0, 4]


@given(st.lists(st.floats(-1e6, 1e6, allow_nan=False), min_size=1, max_size=50), st.integers(0, 60))
def test_top_k_selects_exactly_k_highest(scores: list[float], k: int) -> None:
    array = np.asarray(scores)
    mask = top_k_mask(array, k)
    assert mask.sum() == min(k, array.size)
    if 0 < mask.sum() < array.size:
        assert array[mask].min() >= array[~mask].max()


def test_budget_result_counts() -> None:
    labels = np.array([True, False, True, False] * 2500)
    scores = np.linspace(1, 0, labels.size)
    values = labels.astype(float) * 10
    result = evaluate_budget(labels, scores, values, alerts_per_10k=20)
    assert result.alerts == 20
    assert result.true_positives == 10
    assert result.precision == 0.5
    assert result.recall == 10 / 5000
    assert result.value_share == 100 / 50_000


def test_empty_cases_do_not_divide_by_zero() -> None:
    result = evaluate_budget(np.zeros(0, bool), np.zeros(0), np.zeros(0), 20)
    assert (result.recall, result.precision, result.value_share) == (0.0, 0.0, 0.0)
    assert math.isnan(average_precision(np.zeros(3, bool), np.zeros(3)))


def test_average_precision_of_a_perfect_ranking() -> None:
    labels = np.array([False, True, False, True])
    assert average_precision(labels, np.array([0.1, 0.9, 0.2, 0.8])) == 1.0


def test_budget_table_has_one_row_per_budget() -> None:
    labels = np.array([True] + [False] * 999)
    rows = budget_table(labels, np.arange(1000.0)[::-1], labels * 1.0, (10.0, 100.0))
    assert [row["alerts"] for row in rows] == [1, 10]
    assert rows[0]["recall"] == 1.0


def test_evaluation_config_matches_the_business_case() -> None:
    config = load_config(EvaluationConfig, CONFIG_DIR / "evaluation.yaml")
    assert config.snapshot_step == timedelta(hours=24)
    assert config.headline_alert_budget_per_10k == 20
    assert config.headline_alert_budget_per_10k in config.alert_budgets_per_10k
    assert config.missed_mule_cost_review_units == (10, 50, 100, 500)
    assert max(config.test_snapshots) == config.last_snapshot
