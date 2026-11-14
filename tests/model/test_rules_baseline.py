from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from muletrace.config import CONFIG_DIR, load_config
from muletrace.data import pix_layer_simulator
from muletrace.data.amlworld_loader import RawDataset
from muletrace.data.labels import LabelConfig
from muletrace.data.prepare import prepare_dataset
from muletrace.models.evaluate import EvaluationConfig
from muletrace.models.rules_baseline import Rule, RulesConfig, evaluate_rules, score_rules
from tests.fixtures.amlworld import write_amlworld_files


def test_rule_operators_and_missing_values() -> None:
    frame = pl.DataFrame({"x": [1.0, 5.0, None]})
    at_least = Rule(name="a", description="", feature="x", operator=">=", threshold=5, points=2)
    at_most = Rule(name="b", description="", feature="x", operator="<=", threshold=1, points=1)
    scored = score_rules(frame, RulesConfig(tie_breaker="x", rules=(at_least, at_most)))
    assert scored["rule_a"].to_list() == [False, True, False]
    assert scored["rule_b"].to_list() == [True, False, False]
    assert scored["rules_score"].to_list() == [1, 2, 0]


def test_committed_rules_config_is_valid() -> None:
    config = load_config(RulesConfig, CONFIG_DIR / "rules.yaml")
    assert {rule.name for rule in config.rules} == {
        "fan_in",
        "pass_through",
        "young_account",
        "new_key",
    }


@pytest.fixture
def prepared(tmp_path: Path) -> Path:
    raw = RawDataset("HI-Small", write_amlworld_files(tmp_path / "raw"))
    output = prepare_dataset(raw, tmp_path / "processed").output_dir
    config = load_config(pix_layer_simulator.SimulatorConfig, CONFIG_DIR / "simulator.yaml")
    pix_layer_simulator.run(output, config, load_config(LabelConfig, CONFIG_DIR / "labels.yaml"))
    return output


def test_evaluate_rules_on_a_tiny_dataset(prepared: Path) -> None:
    evaluation = load_config(EvaluationConfig, CONFIG_DIR / "evaluation.yaml").model_copy(
        update={"test_snapshots": (datetime(2022, 9, 2),)}
    )
    labels = load_config(LabelConfig, CONFIG_DIR / "labels.yaml")
    rules = load_config(RulesConfig, CONFIG_DIR / "rules.yaml")
    result = evaluate_rules(prepared, labels, rules, evaluation)
    snapshot = result["snapshots"]["2022-09-02T00:00:00"]
    # Accounts that received a transfer on 1 September: A1, B1, C1 (C1 is not confirmed yet).
    assert snapshot["scored_accounts"] == 3
    assert snapshot["positives"] == 1
    assert len(snapshot["budgets"]) == len(evaluation.alert_budgets_per_10k)
    assert set(snapshot["rule_hit_rates"]) == {f"rule_{r.name}" for r in rules.rules}
