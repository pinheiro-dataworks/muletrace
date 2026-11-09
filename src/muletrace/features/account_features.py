"""Per-account behaviour aggregates, computed strictly from history before the as-of time.

Each function takes the transactions table and an as-of time, goes through
:func:`muletrace.features.asof.history_before`, and returns one row per account. Missing
activity becomes zero counts (an account with no outflow has outflow 0, not null), so the model
sees "no activity" explicitly.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

from muletrace.features.asof import history_before


def _hours(window: timedelta) -> int:
    return int(window.total_seconds() // 3600)


def flow_aggregates(transactions: pl.LazyFrame, as_of: datetime, window: timedelta) -> pl.LazyFrame:
    """Inflow and outflow counts, US-dollar amounts and counterparty diversity in a window.

    Columns are suffixed with the window length in hours, for example ``inflow_usd_24h``.
    Self-transfers are excluded: they move no money between parties.
    """
    suffix = f"_{_hours(window)}h"
    recent = history_before(transactions, as_of, window).filter(~pl.col("is_self_transfer"))
    inflow = recent.group_by(account_id="receiver_id").agg(
        pl.len().alias(f"inflow_count{suffix}"),
        pl.col("amount_paid_usd").sum().alias(f"inflow_usd{suffix}"),
        pl.col("sender_id").n_unique().alias(f"distinct_senders{suffix}"),
    )
    outflow = recent.group_by(account_id="sender_id").agg(
        pl.len().alias(f"outflow_count{suffix}"),
        pl.col("amount_paid_usd").sum().alias(f"outflow_usd{suffix}"),
        pl.col("receiver_id").n_unique().alias(f"distinct_receivers{suffix}"),
    )
    return inflow.join(outflow, on="account_id", how="full", coalesce=True).with_columns(
        pl.exclude("account_id").fill_null(0),
        (
            pl.col(f"outflow_usd{suffix}").fill_null(0)
            / pl.when(pl.col(f"inflow_usd{suffix}") > 0).then(pl.col(f"inflow_usd{suffix}"))
        ).alias(f"pass_through_ratio{suffix}"),
    )


def first_seen(transactions: pl.LazyFrame) -> pl.DataFrame:
    """First transaction time of every account, in either direction.

    Computed once over the whole table: for any as-of time *t*, ``first_seen_at < t`` holds
    exactly when the account had activity before *t*, and then the value equals the minimum
    over the history before *t*. The as-of filter is applied in :func:`account_age_hours`.
    """
    return (
        pl.concat(
            [
                transactions.select(account_id="sender_id", timestamp="timestamp"),
                transactions.select(account_id="receiver_id", timestamp="timestamp"),
            ]
        )
        .group_by("account_id")
        .agg(first_seen_at=pl.col("timestamp").min())
        .collect()
    )


def account_age_hours(first_seen_table: pl.DataFrame, as_of: datetime) -> pl.DataFrame:
    """Hours between an account's first observed transaction and ``as_of``.

    Accounts first seen at or after ``as_of`` are dropped: at ``as_of`` they do not exist yet.
    """
    return first_seen_table.filter(pl.col("first_seen_at") < as_of).select(
        "account_id",
        account_age_hours=(pl.lit(as_of) - pl.col("first_seen_at")).dt.total_minutes() / 60,
    )
