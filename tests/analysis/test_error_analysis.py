from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl

from muletrace.analysis import error_analysis
from muletrace.config import CONFIG_DIR, load_config
from muletrace.models.artifact import load_artifact, save_artifact
from muletrace.models.calibration import IsotonicCalibrator
from muletrace.models.train import TrainingConfig, fit

AS_OF = datetime(2022, 9, 7)
REPORT = {
    "slices_lgbm_tabular_graph": {
        "typology": {
            "CYCLE": {"positives": 3, "recall": 0.5},
            "STACK": {"positives": 9, "recall": 0.2},
        }
    },
    "feature_importance_lgbm_tabular_graph": [
        {"feature": "a", "mean_abs_contribution": 0.3},
        {"feature": "b", "mean_abs_contribution": 0.1},
    ],
}


def _snapshot(n: int = 2000, seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    signal = rng.normal(size=n)
    return pl.DataFrame(
        {
            "account_id": np.arange(n),
            "as_of": [AS_OF] * n,
            "signal": signal,
            "noise": rng.normal(size=n),
            "label": rng.random(n) < 1 / (1 + np.exp(-(3 * signal - 4))),
        }
    )


def test_report_tables() -> None:
    slices = error_analysis.slices_frame(REPORT, "lgbm_tabular_graph")
    assert slices["slice"].to_list() == ["STACK", "CYCLE"]
    assert error_analysis.importance_frame(REPORT, top=1)["feature"].to_list() == ["a"]


def test_alerted_and_caught_versus_missed() -> None:
    snapshot = _snapshot()
    predictions = snapshot.select("account_id", "as_of", "label").with_columns(
        model=pl.lit("m"), score=snapshot["signal"], tie_breaker=pl.lit(0.0)
    )
    flagged = error_analysis.alerted(predictions, "m", alerts_per_10k=500)
    assert flagged["alerted"].sum() == 100
    table = error_analysis.caught_versus_missed(flagged, snapshot.drop("label"), ["signal"])
    caught, missed = table.row(0, named=True), table.row(1, named=True)
    assert caught["outcome"] == "caught"
    assert caught["signal"] > missed["signal"]


def test_top_alert_reasons(tmp_path: Path) -> None:
    training = load_config(TrainingConfig, CONFIG_DIR / "training.yaml").model_copy(
        update={"max_boost_rounds": 30, "early_stopping_rounds": 5}
    )
    train, valid = _snapshot(seed=1), _snapshot(seed=2)
    model = fit(train, valid, ["signal", "noise"], {"num_leaves": 4}, training)
    calibrator = IsotonicCalibrator.fit(model.predict(valid), valid["label"].to_numpy())
    save_artifact(tmp_path, model.booster, calibrator, {"features": ["signal", "noise"]})
    reasons = error_analysis.top_alert_reasons(load_artifact(tmp_path), valid, alerts=5)
    assert reasons.height == 5
    assert reasons["probability"].is_sorted(descending=True)
    assert reasons["reasons"].str.contains("signal=").all()
