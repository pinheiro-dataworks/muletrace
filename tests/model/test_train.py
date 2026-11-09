import numpy as np
import polars as pl
import pytest

from muletrace.config import CONFIG_DIR, load_config
from muletrace.models.evaluate import average_precision
from muletrace.models.train import TrainingConfig, fit, select_params, subsample_negatives
from tests.fixtures.model_data import FEATURES, TRAINING, labelled_frame


@pytest.fixture(scope="module")
def data() -> tuple[pl.DataFrame, pl.DataFrame]:
    return labelled_frame(4000, 1), labelled_frame(2000, 2)


def test_search_space_is_the_full_grid() -> None:
    config = load_config(TrainingConfig, CONFIG_DIR / "training.yaml")
    space = config.search_space()
    assert len(space) == 6
    assert space[0] == {"min_data_in_leaf": 50, "num_leaves": 15}


def test_negative_subsampling_keeps_positives_and_reweights() -> None:
    frame = labelled_frame(5000, 3)
    sampled, weights = subsample_negatives(frame, 0.2, seed=0)
    assert sampled["label"].sum() == frame["label"].sum()
    assert set(np.unique(weights)) <= {1.0, 5.0}
    negatives = (~frame["label"]).sum()
    assert abs((~sampled["label"]).sum() - 0.2 * negatives) < 0.05 * negatives


def test_fit_learns_the_signal_and_selection_logs_trials(data) -> None:
    train, valid = data
    model = fit(train, valid, FEATURES, {"num_leaves": 4}, TRAINING)
    assert average_precision(valid["label"].to_numpy(), model.predict(valid)) > 0.3
    assert model.best_iteration >= 1
    params, trials = select_params(train, valid, FEATURES, TRAINING)
    assert params["num_leaves"] in {4, 8}
    assert len(trials) == 2
