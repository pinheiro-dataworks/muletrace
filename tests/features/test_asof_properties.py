"""Point-in-time invariants: nothing at or after the as-of time may change a snapshot."""

from datetime import timedelta

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st
from polars.testing import assert_frame_equal

from muletrace.data.labels import confirmations, mule_events
from muletrace.features.account_features import account_age_hours, first_seen, flow_aggregates
from muletrace.features.asof import (
    labels_at,
    scored_population,
)
from tests.fixtures.frames import T0, rows_strategy, transactions_frame

AS_OF = T0 + timedelta(days=2)
DAY = timedelta(days=1)


def _future_rows(
    rows: list[tuple[int, int, int, float, bool]],
) -> list[tuple[int, int, int, float, bool]]:
    """Shift rows so that every one happens at or after AS_OF."""
    offset = int((AS_OF - T0).total_seconds() // 60)
    return [(offset + minute, *rest) for minute, *rest in rows]


@settings(max_examples=60, deadline=None)
@given(past=rows_strategy, future=rows_strategy)
def test_flow_aggregates_ignore_transactions_after_as_of(past, future) -> None:
    before = transactions_frame(past)
    after = transactions_frame(past + _future_rows(future))
    expected = flow_aggregates(before.lazy(), AS_OF, DAY).collect().sort("account_id")
    actual = flow_aggregates(after.lazy(), AS_OF, DAY).collect().sort("account_id")
    assert_frame_equal(expected, actual)


@settings(max_examples=60, deadline=None)
@given(past=rows_strategy, future=rows_strategy)
def test_account_age_ignores_transactions_after_as_of(past, future) -> None:
    before = account_age_hours(first_seen(transactions_frame(past).lazy()), AS_OF)
    after = account_age_hours(
        first_seen(transactions_frame(past + _future_rows(future)).lazy()), AS_OF
    )
    assert_frame_equal(before.sort("account_id"), after.sort("account_id"))


@settings(max_examples=60, deadline=None)
@given(rows=rows_strategy, delay_hours=st.integers(min_value=0, max_value=72))
def test_population_excludes_already_confirmed_mules(rows, delay_hours) -> None:
    transactions = transactions_frame(rows).lazy()
    confirmed = confirmations(mule_events(transactions), timedelta(hours=delay_hours))
    population = scored_population(transactions, confirmed, AS_OF, timedelta(days=7))
    known = set(confirmed.filter(pl.col("confirmed_at") <= AS_OF)["account_id"].to_list())
    assert known.isdisjoint(population["account_id"].to_list())


@settings(max_examples=60, deadline=None)
@given(
    rows=rows_strategy,
    delay_hours=st.integers(min_value=0, max_value=72),
    cutoff_hours=st.integers(min_value=0, max_value=96),
)
def test_training_labels_never_use_confirmations_after_the_cutoff(
    rows, delay_hours, cutoff_hours
) -> None:
    transactions = transactions_frame(rows).lazy()
    confirmed = confirmations(mule_events(transactions), timedelta(hours=delay_hours))
    population = scored_population(transactions, confirmed, AS_OF, timedelta(days=7))
    known_by = AS_OF + timedelta(hours=cutoff_hours)
    labelled = labels_at(population, confirmed, AS_OF, timedelta(hours=48), known_by=known_by)
    positives = labelled.filter("label").join(confirmed, on="account_id")
    assert (positives["confirmed_at"] <= known_by).all()
    assert (positives["confirmed_at"] > AS_OF).all()
