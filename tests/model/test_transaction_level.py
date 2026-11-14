import numpy as np
import polars as pl
from hypothesis import given, settings
from polars.testing import assert_frame_equal

from muletrace.models.transaction_level import (
    best_f1_threshold,
    temporal_split,
    transaction_features,
)
from tests.fixtures.frames import rows_strategy, transactions_frame


def _enrich(frame: pl.DataFrame) -> pl.DataFrame:
    currency = pl.Enum(["Euro", "US Dollar"])
    return frame.with_columns(
        payment_format=pl.lit("ACH").cast(pl.Enum(["ACH", "Wire"])),
        payment_currency=pl.lit("US Dollar").cast(currency),
        receiving_currency=pl.lit("US Dollar").cast(currency),
    )


ACCOUNTS = pl.DataFrame(
    {"account_id": list(range(7)), "bank_id": [1, 1, 2, 2, 3, 3, 3]}
).with_columns(pl.col("account_id").cast(pl.UInt32))


def test_features_count_only_earlier_transactions() -> None:
    frame = _enrich(
        transactions_frame([(0, 1, 2, 10.0, False), (60, 1, 3, 20.0, False), (60, 1, 2, 5.0, True)])
    )
    features = transaction_features(frame, ACCOUNTS).sort("tx_id")
    assert features["sender_out_count_24h"].to_list() == [
        0,
        1,
        1,
    ]  # same-minute rows are not "earlier"
    assert features["pair_count_24h"].to_list() == [0, 0, 1]
    assert features["receiver_in_usd_24h"].to_list()[2] == 10.0


@settings(max_examples=30, deadline=None)
@given(past=rows_strategy, future=rows_strategy)
def test_appending_later_transactions_never_changes_earlier_features(past, future) -> None:
    before = _enrich(transactions_frame(past))
    last_minute = max(row[0] for row in past)
    shifted = [(last_minute + 1 + minute, *rest) for minute, *rest in future]
    after = _enrich(transactions_frame(past + shifted))
    expected = (
        transaction_features(before, ACCOUNTS).drop("tx_id").sort("timestamp", "log_amount_usd")
    )
    actual = (
        transaction_features(after, ACCOUNTS)
        .filter(pl.col("timestamp") <= before["timestamp"].max())
        .drop("tx_id")
        .sort("timestamp", "log_amount_usd")
    )
    assert_frame_equal(
        expected.drop("sender_out_counterparts_24h"),
        actual.drop("sender_out_counterparts_24h"),
        check_row_order=False,
    )


def test_temporal_split_keeps_order_and_proportions() -> None:
    frame = pl.DataFrame({"i": range(100)})
    train, valid, test = temporal_split(frame)
    assert (train.height, valid.height, test.height) == (60, 20, 20)
    assert train["i"].max() < valid["i"].min() < test["i"].min()


def test_best_f1_threshold() -> None:
    labels = np.array([True, True, False, False, True])
    scores = np.array([0.9, 0.8, 0.7, 0.2, 0.1])
    threshold, f1 = best_f1_threshold(labels, scores)
    assert threshold == 0.8
    assert f1 == 0.8  # 2 hits, 2 alerts, 3 positives
