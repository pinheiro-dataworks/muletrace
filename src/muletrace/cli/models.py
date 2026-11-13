"""``muletrace features …`` and ``muletrace models …``: snapshots, baselines and experiments."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import yaml

from muletrace.cli._common import GENERATED_DIR, Groups, add_command, logger, write_generated
from muletrace.settings import Settings

if TYPE_CHECKING:
    from muletrace.models.experiment import ExperimentConfig

# Library imports live inside handlers so that `muletrace --help` stays fast.
# ruff: noqa: PLC0415


def experiment_config() -> ExperimentConfig:
    """Every configuration an experiment reads, from ``configs/``."""
    from muletrace.config import CONFIG_DIR, load_config
    from muletrace.data.labels import LabelConfig
    from muletrace.features.config import FeatureConfig
    from muletrace.models.evaluate import EvaluationConfig
    from muletrace.models.experiment import ExperimentConfig
    from muletrace.models.rules_baseline import RulesConfig
    from muletrace.models.train import TrainingConfig

    return ExperimentConfig(
        labels=load_config(LabelConfig, CONFIG_DIR / "labels.yaml"),
        features=load_config(FeatureConfig, CONFIG_DIR / "features.yaml"),
        rules=load_config(RulesConfig, CONFIG_DIR / "rules.yaml"),
        training=load_config(TrainingConfig, CONFIG_DIR / "training.yaml"),
        evaluation=load_config(EvaluationConfig, CONFIG_DIR / "evaluation.yaml"),
    )


def _features_build(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.features.asof import snapshot_times
    from muletrace.features.build import build_snapshots

    config = experiment_config()
    evaluation = config.evaluation
    times = snapshot_times(
        evaluation.first_snapshot, evaluation.last_snapshot, evaluation.snapshot_step
    )
    for name in args.datasets:
        snapshots = build_snapshots(
            settings.processed_dir / name,
            settings.features_dir,
            times,
            config.labels,
            config.features,
        )
        logger.info("%s: %d snapshot rows", name, snapshots.height)
    return 0


def _rules(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.models.rules_baseline import evaluate_rules

    config = experiment_config()
    results = {
        name: evaluate_rules(
            settings.processed_dir / name, config.labels, config.rules, config.evaluation
        )
        for name in args.datasets
    }
    write_generated("rules_baseline.yaml", results, "muletrace models rules")
    return 0


def _backtest(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.models.experiment import run_experiment

    config = experiment_config()
    for name in args.datasets:
        result = run_experiment(settings.processed_dir / name, settings.artifacts_dir, config)
        write_generated(f"backtest_{name}.yaml", result, "muletrace models backtest")
    return 0


def _delay_sweep(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.models.experiment import run_delay_sweep

    config = experiment_config()
    for name in args.datasets:
        backtest = yaml.safe_load((GENERATED_DIR / f"backtest_{name}.yaml").read_text("utf-8"))
        result = run_delay_sweep(
            settings.processed_dir / name,
            settings.artifacts_dir,
            config,
            tuple(args.delays),
            backtest["chosen_params"],
        )
        write_generated(f"delay_sweep_{name}.yaml", result, "muletrace models delay-sweep")
    return 0


def _transaction_check(args: argparse.Namespace, settings: Settings) -> int:
    import polars as pl

    from muletrace.models.transaction_level import run_transaction_check

    config = experiment_config()
    results = {}
    for name in args.datasets:
        folder = settings.processed_dir / name
        results[name] = run_transaction_check(
            pl.read_parquet(folder / "transactions.parquet"),
            pl.read_parquet(folder / "accounts.parquet"),
            config.training,
            name,
        )
    write_generated("transaction_level_check.yaml", results, "muletrace models transaction-check")
    return 0


def register(groups: Groups) -> None:
    """Add the ``features`` and ``models`` groups."""
    features = groups.add_parser("features", help="Point-in-time feature snapshots")
    feature_commands = features.add_subparsers(dest="command", required=True)
    add_command(feature_commands, "build", _features_build, "Build and cache every snapshot")

    models = groups.add_parser("models", help="Baselines, training and evaluation")
    sub = models.add_subparsers(dest="command", required=True)
    add_command(sub, "rules", _rules, "Score the rules baseline on the hold-out")
    add_command(sub, "backtest", _backtest, "Run the model ladder backtest")
    sweep = add_command(
        sub, "delay-sweep", _delay_sweep, "Label-delay sensitivity on the hold-out", ["HI-Small"]
    )
    sweep.add_argument("--delays", nargs="+", type=int, default=[0, 12, 24, 48, 72])
    add_command(
        sub, "transaction-check", _transaction_check, "Reproduce AMLworld's transaction-level task"
    )
