"""Small in-memory transaction tables and a Hypothesis strategy that generates them."""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
from hypothesis import strategies as st

T0 = datetime(2022, 9, 1)
TRANSACTION_SCHEMA = {
    "tx_id": pl.UInt32,
    "timestamp": pl.Datetime("ms"),
    "sender_id": pl.UInt32,
    "receiver_id": pl.UInt32,
    "amount_paid_usd": pl.Float64,
    "is_self_transfer": pl.Boolean,
    "is_laundering": pl.Boolean,
}


def transactions_frame(rows: list[tuple[int, int, int, float, bool]]) -> pl.DataFrame:
    """Build a transactions table from ``(minutes_after_T0, sender, receiver, usd, laundering)``."""
    return pl.DataFrame(
        {
            "tx_id": list(range(len(rows))),
            "timestamp": [T0 + timedelta(minutes=row[0]) for row in rows],
            "sender_id": [row[1] for row in rows],
            "receiver_id": [row[2] for row in rows],
            "amount_paid_usd": [row[3] for row in rows],
            "is_self_transfer": [row[1] == row[2] for row in rows],
            "is_laundering": [row[4] for row in rows],
        },
        schema=TRANSACTION_SCHEMA,
    ).sort("timestamp", "tx_id")


row_strategy = st.tuples(
    st.integers(min_value=0, max_value=4 * 24 * 60),
    st.integers(min_value=0, max_value=6),
    st.integers(min_value=0, max_value=6),
    st.floats(min_value=0.01, max_value=1e6, allow_nan=False),
    st.booleans(),
)
rows_strategy = st.lists(row_strategy, min_size=1, max_size=40)
