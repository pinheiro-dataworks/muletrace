"""End-to-end experiment for one dataset: snapshots → backtest → report → model artefact."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from muletrace.data.labels import LabelConfig
from muletrace.features.asof import snapshot_times
from muletrace.features.build import build_snapshots, cache_key
from muletrace.features.config import FeatureConfig
from muletrace.models import report
from muletrace.models.artifact import save_artifact
from muletrace.models.backtest import LADDER, LGBM_MODELS, Backtest, add_key_age, make_folds
from muletrace.models.evaluate import EvaluationConfig
from muletrace.models.rules_baseline import RulesConfig
from muletrace.models.train import TrainingConfig
from muletrace.tracking import RunLogger

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExperimentConfig:
    """Every configuration an experiment reads."""

    labels: LabelConfig
    features: FeatureConfig
    rules: RulesConfig
    training: TrainingConfig
    evaluation: EvaluationConfig


def account_typology(dataset_dir: Path) -> pl.DataFrame:
    """Typology of the first pattern attempt in which each account receives money."""
    links = pl.read_parquet(dataset_dir / "pattern_transactions.parquet")
    receivers = pl.read_parquet(
        dataset_dir / "transactions.parquet", columns=["tx_id", "receiver_id"]
    )
    return (
        links.join(receivers, on="tx_id")
        .sort("attempt_id")
        .group_by("receiver_id", maintain_order=True)
        .agg(typology=pl.col("typology").first().cast(pl.String))
        .rename({"receiver_id": "account_id"})
    )


def run_experiment(
    dataset_dir: Path, artifacts_dir: Path, config: ExperimentConfig
) -> dict[str, Any]:
    """Run the backtest for one dataset and return the report written to ``docs/generated``."""
    evaluation = config.evaluation
    times = snapshot_times(
        evaluation.first_snapshot, evaluation.last_snapshot, evaluation.snapshot_step
    )
    snapshots = build_snapshots(
        dataset_dir, artifacts_dir / "features", times, config.labels, config.features
    )
    keys = pl.read_parquet(dataset_dir / "pix_layer" / "pix_keys.parquet")
    folds = make_folds(times, config.training.backtest_test_snapshots, config.labels.horizon)
    backtest = Backtest(
        add_key_age(snapshots, keys),
        rules=config.rules,
        features=config.features,
        training=config.training,
        headline_budget=evaluation.headline_alert_budget_per_10k,
        run_logger=RunLogger(f"backtest-{dataset_dir.name}", artifacts_dir / "experiments"),
    )
    result = backtest.run(folds, importance_from=evaluation.test_snapshots)

    output = artifacts_dir / "backtest" / dataset_dir.name
    output.mkdir(parents=True, exist_ok=True)
    result.predictions.write_parquet(output / "predictions.parquet", compression="zstd")
    if result.final_model is not None and result.final_calibrator is not None:
        save_artifact(
            artifacts_dir / "models" / dataset_dir.name,
            result.final_model.booster,
            result.final_calibrator,
            {
                "dataset": dataset_dir.name,
                "model": "lgbm_tabular_graph",
                "features": list(result.final_model.features),
                "params": result.final_model.params,
                "trees": result.final_model.best_iteration,
                "trained_on_snapshots": [s.isoformat() for s in folds[-1].train_at],
                "validated_on_snapshot": folds[-1].valid_at.isoformat(),
                "feature_cache": cache_key(dataset_dir.name, config.labels, config.features),
                "label_config": config.labels.model_dump(),
            },
        )

    held_out = report.holdout(result.predictions, evaluation.test_snapshots)
    lgbm = list(LGBM_MODELS)
    return {
        "dataset": dataset_dir.name,
        "folds": [
            {
                "test": f.test_at.isoformat(),
                "valid": f.valid_at.isoformat(),
                "train": [s.isoformat() for s in f.train_at],
            }
            for f in folds
        ],
        "hold_out_snapshots": [s.isoformat() for s in evaluation.test_snapshots],
        "chosen_params": result.chosen_params,
        "search_trials": result.trials,
        "tuned_rules": result.tuned_rules,
        "per_fold": report.per_fold(result.predictions, evaluation),
        "hold_out": {
            model: report.pooled(held_out, model, evaluation.alert_budgets_per_10k)
            for model in LADDER
        },
        "bootstrap": report.bootstrap_section(
            held_out,
            list(LADDER),
            [
                ("lgbm_tabular_graph", "rules_tuned"),
                ("lgbm_tabular_graph", "rules_hand_set"),
                ("lgbm_tabular_graph", "lgbm_tabular"),
                ("rules_tuned", "rules_hand_set"),
            ],
            evaluation,
        ),
        "expected_cost": report.cost_section(held_out, list(LADDER), evaluation),
        "calibration": report.calibration_section(held_out, lgbm),
        "slices_lgbm_tabular_graph": report.slice_section(
            held_out,
            "lgbm_tabular_graph",
            account_typology(dataset_dir),
            evaluation.headline_alert_budget_per_10k,
        ),
        "slices_rules_tuned": report.slice_section(
            held_out,
            "rules_tuned",
            account_typology(dataset_dir),
            evaluation.headline_alert_budget_per_10k,
        ),
        "feature_importance_lgbm_tabular_graph": result.importance,
    }
