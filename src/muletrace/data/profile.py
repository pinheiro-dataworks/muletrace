"""Headline statistics of a prepared dataset.

Every count quoted in ``docs/data_card.md`` comes from :func:`dataset_profile`, written to
``docs/generated/data_profile.yaml`` by ``muletrace data profile``. Nothing in the data card is
typed by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from muletrace.data.labels import mule_events


def _counts_by(frame: pl.DataFrame, column: str) -> dict[str, dict[str, int]]:
    table = (
        frame.group_by(pl.col(column).cast(pl.String))
        .agg(transactions=pl.len(), laundering=pl.col("is_laundering").sum())
        .sort(column)
    )
    return {
        row[column]: {"transactions": row["transactions"], "laundering": row["laundering"]}
        for row in table.iter_rows(named=True)
    }


def _daily(frame: pl.DataFrame) -> dict[str, dict[str, int]]:
    table = (
        frame.group_by(day=pl.col("timestamp").dt.date())
        .agg(transactions=pl.len(), laundering=pl.col("is_laundering").sum())
        .sort("day")
    )
    return {
        row["day"].isoformat(): {
            "transactions": row["transactions"],
            "laundering": row["laundering"],
        }
        for row in table.iter_rows(named=True)
    }


def dataset_profile(dataset_dir: Path, primary_end: str) -> dict[str, Any]:
    """Return headline statistics for one prepared dataset.

    Args:
        dataset_dir: folder written by the prepare stage.
        primary_end: first day after the primary activity period (ISO date); the tail after it
            is reported separately because AMLworld documents it as laundering-only.
    """
    transactions = pl.read_parquet(dataset_dir / "transactions.parquet")
    accounts = pl.read_parquet(dataset_dir / "accounts.parquet")
    attempts = pl.read_parquet(dataset_dir / "attempts.parquet")
    linked = pl.read_parquet(dataset_dir / "pattern_transactions.parquet")
    n_laundering = int(transactions["is_laundering"].sum())
    tail = transactions.filter(pl.col("timestamp") >= pl.lit(primary_end).str.to_datetime())
    active = pl.concat([transactions["sender_id"], transactions["receiver_id"]]).n_unique()
    return {
        "transactions": transactions.height,
        "laundering_transactions": n_laundering,
        "one_laundering_per_n_transactions": round(transactions.height / n_laundering),
        "first_timestamp": str(transactions["timestamp"].min()),
        "last_timestamp": str(transactions["timestamp"].max()),
        "tail_after_primary_period": {
            "starts": primary_end,
            "transactions": tail.height,
            "laundering": int(tail["is_laundering"].sum()),
        },
        "self_transfers": int(transactions["is_self_transfer"].sum()),
        "accounts_in_accounts_file": accounts.height,
        "accounts_in_transactions": active,
        "entity_types": dict(
            accounts.group_by(pl.col("entity_type").cast(pl.String))
            .len()
            .sort("entity_type")
            .iter_rows()
        ),
        "mule_accounts": mule_events(transactions.lazy()).height,
        "payment_formats": _counts_by(transactions, "payment_format"),
        "daily": _daily(transactions),
        "pattern_attempts": attempts.height,
        "pattern_attempts_by_typology": dict(
            attempts.group_by(pl.col("typology").cast(pl.String)).len().sort("typology").iter_rows()
        ),
        "pattern_transactions": linked.height,
        "pattern_share_of_laundering": round(linked.height / n_laundering, 4),
    }
