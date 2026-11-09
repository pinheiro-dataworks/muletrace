"""Point-in-time snapshot builder: worked examples."""

from datetime import datetime, timedelta

import polars as pl
import pytest

from muletrace.data.labels import confirmations, mule_events
from muletrace.features.account_features import flow_aggregates
from muletrace.features.asof import (
    history_before,
    illicit_inflow_in_horizon,
    labels_at,
    scored_population,
    snapshot_times,
)
from tests.fixtures.frames import T0, transactions_frame

AS_OF = T0 + timedelta(days=2)
DAY = timedelta(days=1)


def test_history_is_strictly_before_as_of() -> None:
    frame = transactions_frame([(0, 1, 2, 1.0, False), (2 * 24 * 60, 1, 2, 1.0, False)])
    kept = history_before(frame.lazy(), AS_OF).collect()
    assert kept["timestamp"].to_list() == [T0]
    windowed = history_before(
        frame.lazy(), AS_OF + timedelta(minutes=1), timedelta(minutes=1)
    ).collect()
    assert windowed["timestamp"].to_list() == [AS_OF]


def test_labels_and_value_in_horizon() -> None:
    rows = [
        (0, 1, 2, 10.0, False),  # account 2 is scored at AS_OF
        (60, 3, 4, 5.0, False),  # account 4 is scored at AS_OF
        (2 * 24 * 60 + 30, 1, 2, 70.0, True),  # account 2 becomes a mule after AS_OF
        (5 * 24 * 60, 1, 4, 99.0, True),  # account 4 only after the horizon
    ]
    transactions = transactions_frame(rows).lazy()
    confirmed = confirmations(mule_events(transactions), timedelta(0))
    population = scored_population(transactions, confirmed, AS_OF, timedelta(days=7))
    labelled = labels_at(population, confirmed, AS_OF, timedelta(hours=48))
    valued = illicit_inflow_in_horizon(transactions, labelled, AS_OF, timedelta(hours=48))
    assert valued.sort("account_id").select("account_id", "label", "illicit_inflow_usd").rows() == [
        (2, True, 70.0),
        (4, False, 0.0),
    ]


def test_flow_aggregates_values() -> None:
    rows = [
        (0, 1, 2, 10.0, False),
        (10, 3, 2, 30.0, False),
        (20, 2, 5, 32.0, False),
        (30, 2, 2, 9.0, False),
    ]
    flows = flow_aggregates(transactions_frame(rows).lazy(), T0 + timedelta(hours=1), DAY).collect()
    account_2 = flows.filter(pl.col("account_id") == 2).row(0, named=True)
    assert account_2["inflow_count_24h"] == 2
    assert account_2["inflow_usd_24h"] == 40.0
    assert account_2["distinct_senders_24h"] == 2
    assert account_2["outflow_usd_24h"] == 32.0
    assert account_2["pass_through_ratio_24h"] == pytest.approx(0.8)
    sender_only = flows.filter(pl.col("account_id") == 1).row(0, named=True)
    assert sender_only["inflow_count_24h"] == 0
    assert sender_only["pass_through_ratio_24h"] is None


def test_snapshot_times() -> None:
    times = snapshot_times(datetime(2022, 9, 2), datetime(2022, 9, 4), DAY)
    assert times == [datetime(2022, 9, 2), datetime(2022, 9, 3), datetime(2022, 9, 4)]
    with pytest.raises(ValueError, match="positive"):
        snapshot_times(datetime(2022, 9, 2), datetime(2022, 9, 4), timedelta(0))
