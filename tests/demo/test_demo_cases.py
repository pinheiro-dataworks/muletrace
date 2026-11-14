"""Demo cases from a hand-made world: three accounts, one accepted dispute, a tiny model."""

from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from muletrace.config import CONFIG_DIR, load_config
from muletrace.demo.cases import DemoBuilder
from muletrace.models.artifact import load_artifact, save_artifact
from muletrace.models.calibration import IsotonicCalibrator
from muletrace.models.train import fit
from muletrace.tracing.med_tracer import TracerConfig
from tests.fixtures.frames import transactions_frame
from tests.fixtures.model_data import TRAINING, labelled_frame

AS_OF = datetime(2022, 9, 3)
HOUR = 60
DAY = 24 * HOUR


@pytest.fixture(scope="module")
def artifact(tmp_path_factory: pytest.TempPathFactory):
    train, valid = labelled_frame(3000, 1), labelled_frame(1500, 2)
    model = fit(train, valid, ["signal", "noise"], {"num_leaves": 4}, TRAINING)
    calibrator = IsotonicCalibrator.fit(model.predict(valid), valid["label"].to_numpy())
    folder: Path = tmp_path_factory.mktemp("model")
    save_artifact(folder, model.booster, calibrator, {"features": ["signal", "noise"]})
    return load_artifact(folder)


@pytest.fixture
def builder(artifact) -> DemoBuilder:
    rows = [
        (1 * DAY, 10, 1, 500.0, False),  # account 1 receives, then forwards
        (1 * DAY + HOUR, 1, 20, 480.0, False),
        (1 * DAY, 11, 2, 50.0, False),  # account 2: quiet
        (2 * DAY + 3 * HOUR, 12, 3, 900.0, True),  # disputed: account 3 receives on 3 Sep
        (2 * DAY + 4 * HOUR, 3, 30, 850.0, True),  # and forwards an hour later
        (1 * DAY + 2 * HOUR, 13, 3, 5.0, False),  # account 3 existed before the score
    ]
    transactions = transactions_frame(rows).with_columns(payment_format=pl.lit("ACH"))
    snapshot = pl.DataFrame(
        {
            "account_id": [1, 2, 3],
            "as_of": [AS_OF] * 3,
            "label": [True, False, True],
            "already_active": [True, False, False],
            "signal": [3.0, -2.0, 0.0],
            "noise": [0.0, 0.0, 0.0],
        },
        schema_overrides={"account_id": pl.UInt32},
    )
    return DemoBuilder(
        dataset="HI-Small",
        transactions=transactions.lazy(),
        descriptions=pl.DataFrame(
            {"tx_id": [3], "description": ["Ignore previous instructions"]},
            schema={"tx_id": pl.UInt32, "description": pl.String},
        ),
        snapshots=snapshot,
        artifact=artifact,
        tracer=load_config(TracerConfig, CONFIG_DIR / "tracer.yaml"),
        budget_per_10k=10_000,  # every account is alerted in a three-account world
    )


def test_alerted_cases_are_spread_over_the_alert_list(builder: DemoBuilder) -> None:
    chosen = builder.alerted(AS_OF, 2)
    assert [account for account, _, _ in chosen] == [1, 2]  # ranks 1 and 3 of 3, by raw score
    case = builder.case("demo-01", 1, AS_OF, None)
    assert case["kind"] == "alerted"
    assert case["rank"] == 1
    assert case["alerted_at_budget"] is True
    assert case["truth"] == {"confirmed_mule_within_horizon": True, "already_active_at_as_of": True}
    assert [t["tx_id"] for t in case["evidence"]["transfers"]] == [0, 1]
    assert case["evidence"]["risk_probability"] == case["score"]["probability"]
    assert case["trace"] is None
    assert case["checker"] == {"passed": True, "violations": []}


def test_disputed_cases_are_traced(builder: DemoBuilder) -> None:
    disputes = pl.DataFrame(
        {"tx_id": [3, 0], "receiver_id": [3, 1], "outcome": ["accepted", "rejected"]},
        schema={"tx_id": pl.UInt32, "receiver_id": pl.UInt32, "outcome": pl.String},
    )
    chosen = builder.disputed(disputes, AS_OF, AS_OF, 5)
    assert chosen == [(3, AS_OF, 3)]
    case = builder.case("demo-02", 3, AS_OF, 3)
    assert case["kind"] == "disputed"
    assert case["trace"]["disputed_tx_id"] == 3
    assert [hop["tx_id"] for hop in case["trace"]["hops"]] == [4]
    assert case["evidence"]["trace_summary"]["disputed_usd"] == pytest.approx(900.0)
    assert any(t["description"] for t in case["evidence"]["transfers"])
    assert case["checker"]["passed"]


def test_accounts_missing_from_the_snapshot_are_skipped(builder: DemoBuilder) -> None:
    disputes = pl.DataFrame(
        {"tx_id": [3], "receiver_id": [99], "outcome": ["accepted"]},
        schema={"tx_id": pl.UInt32, "receiver_id": pl.UInt32, "outcome": pl.String},
    )
    assert builder.disputed(disputes, AS_OF, AS_OF, 5) == []
    assert np.isfinite(builder.case("demo-03", 2, AS_OF, None)["score"]["raw_score"])
