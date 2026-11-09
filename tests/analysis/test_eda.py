from datetime import timedelta

import polars as pl
import pytest

from muletrace.analysis import eda
from muletrace.data.labels import confirmations, mule_events
from tests.fixtures.frames import T0, transactions_frame

ROWS = [
    (0, 1, 2, 10.0, False),
    (30, 3, 2, 20.0, False),
    (60, 4, 5, 50.0, True),  # account 5 becomes a mule at 01:00
    (90, 5, 6, 45.0, True),  # and forwards 30 minutes later
    (23 * 60, 2, 2, 5.0, False),  # self-transfer at 23:00
    (25 * 60, 7, 8, 1.0, False),  # second day
]


@pytest.fixture
def transactions() -> pl.LazyFrame:
    return transactions_frame(ROWS).lazy()


def test_daily_laundering(transactions: pl.LazyFrame) -> None:
    daily = eda.daily_laundering(transactions)
    assert daily["transactions"].to_list() == [5, 1]
    assert daily["laundering"].to_list() == [2, 0]
    assert daily["laundering_per_10k"][0] == pytest.approx(4000.0)


def test_typology_mix() -> None:
    attempts = pl.DataFrame({"typology": ["CYCLE", "CYCLE", "STACK"], "n_rows": [3, 5, 2]})
    mix = eda.typology_mix(attempts)
    assert mix.row(0, named=True) == {
        "typology": "CYCLE",
        "attempts": 2,
        "median_transactions": 4.0,
        "max_transactions": 5,
    }


def test_format_mix_and_hours(transactions: pl.LazyFrame) -> None:
    frame = transactions.collect().with_columns(
        payment_format=pl.Series(["ACH", "ACH", "ACH", "Wire", "Cash", "Cash"])
    )
    mix = eda.format_mix(frame.lazy())
    ach = mix.filter(pl.col("payment_format") == "ACH").row(0, named=True)
    assert ach["share_of_laundering"] == 0.5
    hours = eda.hour_of_day(transactions)
    assert hours.filter(pl.col("hour") == 1)["laundering_share"].item() == 1.0
    assert 23 not in hours["hour"].to_list()  # the only 23:00 row is a self-transfer


def test_snapshot_profile_and_comparison(transactions: pl.LazyFrame) -> None:
    confirmed = confirmations(mule_events(transactions), timedelta(hours=24))
    profile = eda.snapshot_profile(
        transactions, confirmed, T0 + timedelta(hours=2), timedelta(days=7), timedelta(hours=48)
    )
    mule = profile.filter(pl.col("account_id") == 5).row(0, named=True)
    assert mule["label"] is True
    assert mule["already_active"] is True
    assert mule["inflow_usd_24h"] == 50.0
    table = eda.compare_groups(profile, ["inflow_usd_24h"])
    # Account 2 is ordinary; accounts 5 and 6 both receive laundered money on day one.
    assert table["accounts"].to_list() == [1, 2]


def test_time_to_forward_for_mules_and_controls(transactions: pl.LazyFrame) -> None:
    mules = mule_events(transactions)
    anchors = mules.select("account_id", anchor_at="became_mule_at")
    forwarded = eda.time_to_forward(transactions, anchors)
    assert forwarded["hours_to_forward"].to_list() == [0.5, None]  # account 6 never forwards
    controls = eda.first_inflows(transactions, exclude=mules)
    assert sorted(controls["account_id"].to_list()) == [2, 8]
    control_times = eda.time_to_forward(transactions, controls)
    assert control_times.filter(pl.col("account_id") == 8)["hours_to_forward"].item() is None


def test_mule_rate_by_entity_type() -> None:
    accounts = pl.DataFrame(
        {
            "account_id": [1, 2, 3, 4],
            "entity_type": ["Corporation", "Corporation", "Individual", "Individual"],
        }
    )
    rates = eda.mule_rate_by_entity_type(accounts, pl.DataFrame({"account_id": [3]}))
    assert rates.row(0, named=True) == {
        "entity_type": "Individual",
        "accounts": 2,
        "mules": 1,
        "mules_per_10k": 5000.0,
    }
