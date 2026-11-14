import pytest

from muletrace.config import CONFIG_DIR, load_config
from muletrace.data import pix_layer_simulator
from muletrace.data.amlworld_loader import RawDataset
from muletrace.data.labels import LabelConfig
from muletrace.data.prepare import prepare_dataset
from muletrace.evals.gold import build_gold_cases, read_gold_cases, write_gold_cases
from tests.fixtures.amlworld import write_amlworld_files


@pytest.fixture(scope="module")
def cases(tmp_path_factory: pytest.TempPathFactory) -> list:
    base = tmp_path_factory.mktemp("gold")
    dataset_dir = prepare_dataset(
        RawDataset("HI-Small", write_amlworld_files(base / "raw")), base / "p"
    ).output_dir
    pix_layer_simulator.run(
        dataset_dir,
        load_config(pix_layer_simulator.SimulatorConfig, CONFIG_DIR / "simulator.yaml"),
        load_config(LabelConfig, CONFIG_DIR / "labels.yaml"),
    )
    built = build_gold_cases(dataset_dir, per_typology=5, negatives=2, seed=0)
    write_gold_cases(built, base / "gold.jsonl")
    return read_gold_cases(base / "gold.jsonl")


def test_gold_cases_from_the_fixture_patterns(cases: list) -> None:
    positives = [c for c in cases if c.is_positive]
    assert {c.typology for c in positives} == {"STACK", "FAN-OUT"}
    stack = next(c for c in positives if c.typology == "STACK")
    assert stack.relevant_tx_ids == (2, 3)  # both identical rows, one-to-one
    assert {t.tx_id for t in stack.evidence.transfers} >= {2, 3}
    negatives = [c for c in cases if not c.is_positive]
    assert all(c.expected_actions == ("close", "monitor") for c in negatives)
