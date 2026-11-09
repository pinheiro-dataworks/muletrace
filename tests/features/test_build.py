from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from muletrace.config import CONFIG_DIR, load_config
from muletrace.data.amlworld_loader import RawDataset
from muletrace.data.labels import LabelConfig
from muletrace.data.prepare import prepare_dataset
from muletrace.features.build import (
    GRAPH_FEATURES,
    OUTCOME_COLUMNS,
    build_snapshots,
    cache_key,
    model_features,
    tabular_features,
)
from muletrace.features.config import FeatureConfig
from tests.fixtures.amlworld import write_amlworld_files

FEATURES = load_config(FeatureConfig, CONFIG_DIR / "features.yaml")
LABELS = load_config(LabelConfig, CONFIG_DIR / "labels.yaml")


def test_feature_lists_never_contain_outcomes_or_keys() -> None:
    names = model_features(FEATURES, include_graph=True)
    assert len(names) == len(set(names))
    assert not set(names) & {*OUTCOME_COLUMNS, "account_id", "as_of"}
    assert model_features(FEATURES, include_graph=False) == tabular_features(FEATURES)
    assert names[-len(GRAPH_FEATURES) :] == list(GRAPH_FEATURES)


@pytest.fixture
def dataset_dir(tmp_path: Path) -> Path:
    raw = RawDataset("HI-Small", write_amlworld_files(tmp_path / "raw"))
    return prepare_dataset(raw, tmp_path / "processed").output_dir


def test_build_snapshots_and_cache(dataset_dir: Path, tmp_path: Path) -> None:
    times = [datetime(2022, 9, 2)]
    first = build_snapshots(dataset_dir, tmp_path / "cache", times, LABELS, FEATURES)
    expected = [
        "account_id",
        "as_of",
        *OUTCOME_COLUMNS,
        *model_features(FEATURES, include_graph=True),
    ]
    assert first.columns == expected
    assert first["account_id"].to_list() == sorted(first["account_id"].to_list())
    positives = first.filter("label")
    assert positives.height == 1
    assert positives["label_confirmed_at"].item() == datetime(2022, 9, 2, 1)
    assert first.filter(~pl.col("label"))["label_confirmed_at"].null_count() == first.height - 1
    cached = list((tmp_path / "cache" / cache_key("HI-Small", LABELS, FEATURES)).iterdir())
    assert len(cached) == 1
    again = build_snapshots(dataset_dir, tmp_path / "cache", times, LABELS, FEATURES)
    assert again.equals(first)


def test_cache_key_changes_with_the_label_definition() -> None:
    other = LABELS.model_copy(update={"confirmation_delay_hours": 48})
    assert cache_key("HI-Small", LABELS, FEATURES) != cache_key("HI-Small", other, FEATURES)


def test_build_snapshots_builds_several_times_in_one_pass(
    dataset_dir: Path, tmp_path: Path
) -> None:
    times = [datetime(2022, 9, 2), datetime(2022, 9, 3)]
    snapshots = build_snapshots(dataset_dir, tmp_path / "cache", times, LABELS, FEATURES)
    assert snapshots["as_of"].unique().sort().to_list() == times
