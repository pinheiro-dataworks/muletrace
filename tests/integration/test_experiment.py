"""End-to-end: generated world → ingestion → Pix layer → features → backtest → artefact."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from muletrace.config import CONFIG_DIR, load_config
from muletrace.data import pix_layer_simulator
from muletrace.data.amlworld_loader import RawDataset
from muletrace.data.labels import LabelConfig
from muletrace.data.prepare import prepare_dataset
from muletrace.features.config import FeatureConfig
from muletrace.models.artifact import load_artifact
from muletrace.models.evaluate import BootstrapConfig, EvaluationConfig
from muletrace.models.experiment import ExperimentConfig, run_delay_sweep, run_experiment
from muletrace.models.rules_baseline import RulesConfig
from muletrace.models.train import TrainingConfig
from muletrace.models.transaction_level import run_transaction_check
from tests.fixtures.world import generate_world

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("world")
    raw = RawDataset("HI-Small", generate_world(base / "raw"))
    dataset_dir = prepare_dataset(raw, base / "processed").output_dir
    labels = load_config(LabelConfig, CONFIG_DIR / "labels.yaml")
    simulator = load_config(pix_layer_simulator.SimulatorConfig, CONFIG_DIR / "simulator.yaml")
    pix_layer_simulator.run(dataset_dir, simulator, labels)
    return dataset_dir


@pytest.fixture(scope="module")
def config() -> ExperimentConfig:
    training = load_config(TrainingConfig, CONFIG_DIR / "training.yaml").model_copy(
        update={
            "search": {"num_leaves": (4,)},
            "max_boost_rounds": 40,
            "early_stopping_rounds": 10,
            "negative_sample_rate": 0.5,
            "rules_search": {"fan_in": (2.0, 3.0)},
        }
    )
    evaluation = load_config(EvaluationConfig, CONFIG_DIR / "evaluation.yaml").model_copy(
        update={"bootstrap": BootstrapConfig(replicates=10, seed=0)}
    )
    return ExperimentConfig(
        labels=load_config(LabelConfig, CONFIG_DIR / "labels.yaml"),
        features=load_config(FeatureConfig, CONFIG_DIR / "features.yaml"),
        rules=load_config(RulesConfig, CONFIG_DIR / "rules.yaml"),
        training=training,
        evaluation=evaluation,
    )


def test_run_experiment_writes_a_full_report_and_artifact(
    world: Path, config: ExperimentConfig, tmp_path: Path
) -> None:
    result = run_experiment(world, tmp_path, config)
    assert len(result["folds"]) == len(config.training.backtest_test_snapshots)
    assert set(result["hold_out"]) == {
        "rules_hand_set",
        "rules_tuned",
        "lgbm_tabular",
        "lgbm_tabular_graph",
    }
    assert "lgbm_tabular_graph minus rules_tuned" in result["bootstrap"]["recall_difference"]
    assert result["feature_importance_lgbm_tabular_graph"]
    artifact = load_artifact(tmp_path / "models" / "HI-Small")
    assert artifact.metadata["model"] == "lgbm_tabular_graph"
    predictions = pl.read_parquet(tmp_path / "backtest" / "HI-Small" / "predictions.parquet")
    graph = predictions.filter(pl.col("model") == "lgbm_tabular_graph")
    assert np.all((graph["probability"].to_numpy() >= 0) & (graph["probability"].to_numpy() <= 1))
    assert (tmp_path / "experiments" / "backtest-HI-Small.jsonl").is_file()


def test_delay_sweep_reports_every_delay(
    world: Path, config: ExperimentConfig, tmp_path: Path
) -> None:
    params = {"lgbm_tabular": {"num_leaves": 4}, "lgbm_tabular_graph": {"num_leaves": 4}}
    result = run_delay_sweep(world, tmp_path, config, (0, 24), params)
    assert set(result["delays"]) == {"0h", "24h"}
    assert (
        result["delays"]["0h"]["already_active_share"]
        <= result["delays"]["24h"]["already_active_share"]
    )
    assert "lgbm_tabular_graph" in result["delays"]["24h"]["recall"]


def test_transaction_check_runs_on_the_temporal_split(
    world: Path, config: ExperimentConfig
) -> None:
    result = run_transaction_check(
        pl.read_parquet(world / "transactions.parquet"),
        pl.read_parquet(world / "accounts.parquet"),
        config.training,
        "HI-Small",
    )
    rows = result["rows"]
    assert rows["train"] > rows["valid"] > 0
    assert 0 <= result["test"]["f1_percent"] <= 100
    assert result["paper_reference"]["GFP + LightGBM"] == 62.86
