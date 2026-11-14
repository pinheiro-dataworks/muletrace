import polars as pl
import pytest

from muletrace.models.explain import contributions, global_importance, reason_codes
from muletrace.models.train import fit
from tests.fixtures.model_data import FEATURES, TRAINING, labelled_frame


@pytest.fixture(scope="module")
def data() -> tuple[pl.DataFrame, pl.DataFrame]:
    return labelled_frame(4000, 1), labelled_frame(2000, 2)


def test_shap_contributions_rank_the_signal_first(data) -> None:
    train, valid = data
    model = fit(train, valid, FEATURES, {"num_leaves": 4}, TRAINING)
    contrib = contributions(model, valid)
    assert contrib.shape == (valid.height, len(FEATURES))
    assert global_importance(contrib, model.features)[0]["feature"] == "signal"
    codes = reason_codes(contrib[:5], valid[:5], model.features, top=2)
    assert len(codes) == 5
    assert all(code["contribution"] > 0 for row in codes for code in row)
