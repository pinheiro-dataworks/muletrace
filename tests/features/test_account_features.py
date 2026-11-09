from datetime import timedelta

import polars as pl
import pytest

from muletrace.config import CONFIG_DIR, load_config
from muletrace.features.account_features import forwarding_speed, inflow_details
from muletrace.features.config import FeatureConfig
from tests.fixtures.frames import T0, transactions_frame

FEATURES = load_config(FeatureConfig, CONFIG_DIR / "features.yaml")


def test_inflow_details() -> None:
    frame = transactions_frame(
        [
            (21 * 60, 1, 2, 9_500.0, False),  # night, just below the threshold
            (12 * 60, 3, 2, 300.0, False),  # day, round amount
            (13 * 60, 3, 2, 50.5, False),
        ]
    ).with_columns(
        amount_paid=pl.col("amount_paid_usd"),
        payment_format=pl.Series(["ACH", "Wire", "Wire"]),
    )
    banks = pl.DataFrame({"account_id": [1, 2, 3], "bank_id": [10, 20, 20]})
    details = inflow_details(frame.lazy(), banks, T0 + timedelta(days=1), FEATURES).collect()
    row = details.row(0, named=True)
    assert row["account_id"] == 2
    assert row["night_inflow_share"] == pytest.approx(1 / 3)
    assert row["just_below_threshold_share"] == pytest.approx(1 / 3)
    assert row["round_amount_inflow_share"] == pytest.approx(2 / 3)  # 9,500 and 300
    assert row["ach_inflow_share"] == pytest.approx(1 / 3)
    assert row["distinct_inflow_formats"] == 2
    assert row["cross_bank_inflow_share"] == pytest.approx(1 / 3)
    assert row["max_inflow_usd"] == 9_500.0


def test_forwarding_speed_only_sees_outflows_before_as_of() -> None:
    frame = transactions_frame(
        [
            (0, 1, 2, 10.0, False),  # inflow at 00:00
            (120, 2, 3, 9.0, False),  # forwarded two hours later
            (180, 4, 2, 10.0, False),  # second inflow, forwarded only after AS_OF
            (3000, 2, 5, 9.0, False),
        ]
    )
    as_of = T0 + timedelta(hours=10)
    speed = forwarding_speed(frame.lazy(), as_of, timedelta(days=7)).collect()
    row = speed.filter(pl.col("account_id") == 2).row(0, named=True)
    assert row["median_hours_to_forward"] == 2.0
    assert row["forwarded_within_24h_share"] == 0.5
