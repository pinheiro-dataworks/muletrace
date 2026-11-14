from datetime import timedelta

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from muletrace.config import CONFIG_DIR, load_config
from muletrace.tracing.med_tracer import TracerConfig, trace
from tests.fixtures.frames import T0, rows_strategy, transactions_frame

CONFIG = TracerConfig(max_hops=5, hop_window_hours=72, min_transaction_usd=10, max_transactions=500)
S, A, B, C, X = 0, 1, 2, 3, 4


def _recoverable(result) -> dict[int, float]:
    return {
        r["account_id"]: round(r["recoverable_usd"], 6) for r in result.nodes.iter_rows(named=True)
    }


def test_known_answer_fifo_split() -> None:
    rows = [
        (0, S, A, 100.0, True),  # disputed transfer, tx 0
        (60, A, B, 60.0, True),
        (120, B, C, 50.0, True),
        (180, A, X, 70.0, False),  # only 40 tainted left at A
    ]
    result = trace(transactions_frame(rows).lazy(), 0, CONFIG)
    assert _recoverable(result) == {A: 0.0, B: 10.0, C: 50.0, X: 40.0}
    assert result.hops["tainted_usd"].to_list() == [60.0, 50.0, 40.0]
    assert result.hops["hop"].to_list() == [1, 2, 1]
    assert result.left_trace_usd == 0.0
    assert result.summary()["max_hop_reached"] == 2


def test_outflows_before_the_dispute_and_outside_the_window_are_ignored() -> None:
    rows = [
        (100, S, A, 100.0, True),  # disputed, tx 0
        (50, A, B, 80.0, False),  # before the dispute
        (100 + 73 * 60, A, C, 90.0, False),  # after the 72-hour window
    ]
    result = trace(transactions_frame(rows).lazy(), 0, CONFIG)
    assert result.hops.height == 0
    assert _recoverable(result) == {A: 100.0}


def test_hop_limit_and_minimum_amount_count_as_leaving_the_trace() -> None:
    rows = [
        (0, S, A, 100.0, True),
        (10, A, B, 5.0, False),  # below the minimum amount: leaves the trace
        (20, A, C, 95.0, False),  # hop 1, followed
        (30, C, X, 90.0, False),  # hop 2 exceeds max_hops=1: leaves the trace
    ]
    shallow = CONFIG.model_copy(update={"max_hops": 1})
    result = trace(transactions_frame(rows).lazy(), 0, shallow)
    assert result.left_trace_usd == pytest.approx(95.0)
    assert _recoverable(result) == {A: 0.0, C: 5.0}


def test_transaction_cap_is_reported() -> None:
    rows = [(0, S, A, 100.0, True), (10, A, B, 50.0, False), (20, A, C, 50.0, False)]
    capped = CONFIG.model_copy(update={"max_transactions": 1})
    result = trace(transactions_frame(rows).lazy(), 0, capped)
    assert result.followed_transactions == 1
    assert result.left_trace_usd == 50.0
    assert result.summary()["notes"]


def test_unknown_transaction_raises() -> None:
    with pytest.raises(KeyError):
        trace(transactions_frame([(0, S, A, 1.0, False)]).lazy(), 99, CONFIG)


def test_committed_config_loads() -> None:
    config = load_config(TracerConfig, CONFIG_DIR / "tracer.yaml")
    assert config.hop_window == timedelta(hours=72)


@settings(max_examples=80, deadline=None)
@given(rows=rows_strategy, hops=st.integers(1, 4), window=st.integers(1, 96))
def test_conservation_and_causality(rows, hops, window) -> None:
    frame = transactions_frame([(0, 0, 1, 500.0, True), *rows])
    config = CONFIG.model_copy(update={"max_hops": hops, "hop_window_hours": window})
    result = trace(frame.lazy(), 0, config)
    assert result.recoverable_usd + result.left_trace_usd == pytest.approx(500.0)
    if result.hops.height:
        assert (result.hops["tainted_usd"] <= result.hops["amount_usd"] + 1e-6).all()
        assert (result.hops["timestamp"] > T0).all()
        assert (result.hops["hop"] <= hops).all()
        assert result.hops["tainted_usd"].sum() <= 500.0 * hops + 1e-6
    assert (result.nodes["recoverable_usd"] >= -1e-9).all()
    assert pl.Series(result.nodes["account_id"]).is_unique().all()


def test_oldest_lot_is_spent_first_and_money_can_come_back() -> None:
    rows = [
        (0, S, A, 100.0, True),
        (10, A, B, 60.0, False),  # A keeps 40 from its first lot
        (20, B, A, 50.0, False),  # 50 tainted returns to A as a second lot (hop 2)
        (30, A, C, 20.0, False),  # paid from the oldest lot only
    ]
    result = trace(transactions_frame(rows).lazy(), 0, CONFIG)
    assert result.hops.filter(pl.col("receiver_id") == C)["hop"].item() == 1
    assert _recoverable(result) == {A: 70.0, B: 10.0, C: 20.0}
