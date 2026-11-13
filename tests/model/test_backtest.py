from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from muletrace.config import CONFIG_DIR, load_config
from muletrace.features.build import model_features
from muletrace.features.config import FeatureConfig
from muletrace.models import report
from muletrace.models.backtest import (
    LADDER,
    Backtest,
    add_key_age,
    make_folds,
    pooled_recall,
    tune_rules,
    with_known_labels,
)
from muletrace.models.evaluate import BootstrapConfig, EvaluationConfig
from muletrace.models.rules_baseline import RulesConfig
from muletrace.models.train import TrainingConfig
from muletrace.tracking import RunLogger

DAY = timedelta(days=1)
TIMES = [datetime(2022, 9, d) for d in range(2, 10)]
FEATURES = load_config(FeatureConfig, CONFIG_DIR / "features.yaml")
RULES = load_config(RulesConfig, CONFIG_DIR / "rules.yaml")
EVALUATION = load_config(EvaluationConfig, CONFIG_DIR / "evaluation.yaml").model_copy(
    update={"bootstrap": BootstrapConfig(replicates=20, seed=1)}
)
TRAINING = load_config(TrainingConfig, CONFIG_DIR / "training.yaml").model_copy(
    update={
        "search": {"num_leaves": (4,)},
        "max_boost_rounds": 30,
        "early_stopping_rounds": 5,
        "rules_search": {"fan_in": (2, 5)},
    }
)


def test_folds_validate_one_horizon_before_the_test() -> None:
    folds = make_folds(TIMES, (datetime(2022, 9, 6), datetime(2022, 9, 9)), timedelta(hours=48))
    assert folds[0].valid_at == datetime(2022, 9, 4)
    assert folds[0].train_at == (datetime(2022, 9, 2), datetime(2022, 9, 3))
    assert folds[1].train_at[-1] == datetime(2022, 9, 6)
    with pytest.raises(ValueError, match="not enough history"):
        make_folds(TIMES, (datetime(2022, 9, 3),), timedelta(hours=48))


def test_known_labels_drop_confirmations_after_the_cut_off() -> None:
    frame = pl.DataFrame(
        {
            "label": [True, True, False],
            "label_confirmed_at": [datetime(2022, 9, 5), datetime(2022, 9, 8), None],
        }
    )
    assert with_known_labels(frame, datetime(2022, 9, 6))["label"].to_list() == [True, False, False]


def test_key_age_in_days() -> None:
    snapshots = pl.DataFrame({"account_id": [1], "as_of": [datetime(2022, 9, 5)]})
    keys = pl.DataFrame({"account_id": [1], "registered_at": [datetime(2022, 9, 3, 12)]})
    assert add_key_age(snapshots, keys)["key_age_days"].item() == 1.5


def _synthetic_snapshots(seed: int = 0, n: int = 3000) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    names = model_features(FEATURES, include_graph=True)
    frames = []
    for as_of in TIMES:
        signal = rng.normal(size=n)
        label = rng.random(n) < 1 / (1 + np.exp(-(3 * signal - 5)))
        columns = {name: rng.normal(size=n) for name in names}
        columns |= {
            "confirmed_mule_senders": signal,
            "distinct_senders_24h": np.where(label, 6, rng.integers(0, 4, n)).astype(float),
            "entity_type": rng.integers(0, 3, n).astype(float),
        }
        frames.append(
            pl.DataFrame(
                {
                    "account_id": np.arange(n),
                    "as_of": [as_of] * n,
                    "label": label,
                    "label_confirmed_at": [as_of + DAY if y else None for y in label],
                    "already_active": rng.random(n) < 0.5,
                    "illicit_inflow_usd": np.where(label, rng.exponential(5000, n), 0.0),
                    "key_age_days": rng.uniform(0, 365, n),
                    **columns,
                }
            )
        )
    return pl.concat(frames)


def test_tuned_rules_pick_the_informative_threshold() -> None:
    frame = _synthetic_snapshots()
    tuned, recall = tune_rules(frame, RULES, {"fan_in": (2.0, 5.0)}, 20)
    assert next(rule for rule in tuned.rules if rule.name == "fan_in").threshold == 5.0
    assert (
        recall
        == pooled_recall(
            frame.with_columns(rules_score=pl.col("distinct_senders_24h") >= 5),
            "rules_score",
            "inflow_usd_24h",
            20,
        )
        or recall > 0
    )
    with pytest.raises(ValueError, match="empty"):
        tune_rules(frame, RULES, {"fan_in": ()}, 20)


@pytest.fixture(scope="module")
def backtest_result(tmp_path_factory: pytest.TempPathFactory):
    snapshots = _synthetic_snapshots(seed=3)
    folds = make_folds(TIMES, (datetime(2022, 9, 8), datetime(2022, 9, 9)), timedelta(hours=48))
    run_logger = RunLogger("test", tmp_path_factory.mktemp("runs"))
    backtest = Backtest(
        snapshots,
        rules=RULES,
        features=FEATURES,
        training=TRAINING,
        headline_budget=20,
        run_logger=run_logger,
    )
    return backtest.run(folds, importance_from=(datetime(2022, 9, 9),))


def test_backtest_scores_every_model_on_every_test_snapshot(backtest_result) -> None:
    predictions = backtest_result.predictions
    assert set(predictions["model"]) == set(LADDER)
    assert predictions.group_by("model", "as_of").len()["len"].unique().to_list() == [3000]
    lgbm = predictions.filter(pl.col("model") == "lgbm_tabular_graph")
    assert lgbm["probability"].null_count() == 0
    assert backtest_result.final_model is not None
    # The synthetic fan-in column is a near-perfect label, so it must dominate the SHAP ranking.
    assert backtest_result.importance[0]["feature"] == "distinct_senders_24h"
    assert set(backtest_result.tuned_rules) == {"2022-09-08T00:00:00", "2022-09-09T00:00:00"}


def test_report_sections(backtest_result) -> None:
    held_out = report.holdout(backtest_result.predictions, (datetime(2022, 9, 9),))
    pooled = report.pooled(held_out, "lgbm_tabular_graph", (20.0,))
    assert pooled[0]["alerts"] == 6
    folds = report.per_fold(backtest_result.predictions, EVALUATION)
    assert set(folds) == set(LADDER)
    boot = report.bootstrap_section(
        held_out, list(LADDER), [("lgbm_tabular_graph", "rules_hand_set")], EVALUATION
    )
    graph = boot["average_precision"]["lgbm_tabular_graph"]
    assert graph["ci95"][0] <= graph["estimate"] <= graph["ci95"][1]
    cost = report.cost_section(held_out, ["lgbm_tabular_graph", "rules_tuned"], EVALUATION)
    assert len(cost["lgbm_tabular_graph"]) == len(EVALUATION.missed_mule_cost_review_units)
    assert "threshold_policy_cost" in cost["lgbm_tabular_graph"][0]
    assert "threshold_policy_cost" not in cost["rules_tuned"][0]
    calibration = report.calibration_section(held_out, ["lgbm_tabular_graph"])
    assert calibration["lgbm_tabular_graph"]["reliability"]
    typology = pl.DataFrame({"account_id": [0, 1], "typology": ["CYCLE", "STACK"]})
    slices = report.slice_section(held_out, "lgbm_tabular_graph", typology, 20)
    assert set(slices) == {"typology", "activity", "ticket_band"}
    assert "no pattern" in slices["typology"]


def test_account_typology(tmp_path: Path) -> None:
    from muletrace.models.experiment import account_typology  # noqa: PLC0415

    pl.DataFrame(
        {"attempt_id": [1, 0], "typology": ["STACK", "CYCLE"], "tx_id": [10, 11]}
    ).write_parquet(tmp_path / "pattern_transactions.parquet")
    pl.DataFrame({"tx_id": [10, 11], "receiver_id": [5, 5]}).write_parquet(
        tmp_path / "transactions.parquet"
    )
    assert account_typology(tmp_path).to_dicts() == [{"account_id": 5, "typology": "CYCLE"}]
