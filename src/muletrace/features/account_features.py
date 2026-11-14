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
from muletrace.features.config import FeatureConfig, NightWindow

_FAST_FORWARD_HOURS = 24


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


def _is_night(night: NightWindow) -> pl.Expr:
    hour = pl.col("timestamp").dt.hour()
    return (hour >= night.start_hour) | (hour < night.end_hour)


def inflow_details(
    transactions: pl.LazyFrame,
    account_banks: pl.DataFrame,
    as_of: datetime,
    config: FeatureConfig,
) -> pl.LazyFrame:
    """Shape of the recent inflow: timing, amounts, formats and counterparties.

    All shares are over the account's non-self inflows in the detail window, so they are null
    for accounts without inflow there.
    """
    structuring = config.structuring
    banks = account_banks.lazy().select("account_id", "bank_id")
    lower = structuring.threshold_usd * (1 - structuring.just_below_share)
    inflows = (
        history_before(transactions, as_of, config.detail_window)
        .filter(~pl.col("is_self_transfer"))
        .join(banks.rename({"account_id": "sender_id", "bank_id": "sender_bank"}), on="sender_id")
        .join(
            banks.rename({"account_id": "receiver_id", "bank_id": "receiver_bank"}),
            on="receiver_id",
        )
    )
    return inflows.group_by(account_id="receiver_id").agg(
        night_inflow_share=_is_night(config.night).mean(),
        round_amount_inflow_share=(
            (pl.col("amount_paid") % structuring.round_amount_unit) == 0
        ).mean(),
        just_below_threshold_share=pl.col("amount_paid_usd")
        .is_between(lower, structuring.threshold_usd, closed="left")
        .mean(),
        ach_inflow_share=(pl.col("payment_format").cast(pl.String) == "ACH").mean(),
        distinct_inflow_formats=pl.col("payment_format").n_unique(),
        cross_bank_inflow_share=(pl.col("sender_bank") != pl.col("receiver_bank")).mean(),
        max_inflow_usd=pl.col("amount_paid_usd").max(),
    )


def forwarding_speed(
    transactions: pl.LazyFrame, as_of: datetime, window: timedelta
) -> pl.LazyFrame:
    """How fast recent inflows are followed by an outgoing transfer, before ``as_of``.

    For every inflow in the window, the next outgoing transfer of the same account that
    happened before ``as_of`` is found; inflows without one count as not forwarded.
    """
    history = history_before(transactions, as_of).filter(~pl.col("is_self_transfer"))
    inflows = (
        history.filter(pl.col("timestamp") >= as_of - window)
        .select(account_id="receiver_id", received_at="timestamp")
        .sort("received_at")
    )
    outflows = history.select(account_id="sender_id", forwarded_at="timestamp").sort("forwarded_at")
    hours = (pl.col("forwarded_at") - pl.col("received_at")).dt.total_minutes() / 60
    return (
        inflows.join_asof(
            outflows,
            left_on="received_at",
            right_on="forwarded_at",
            by="account_id",
            strategy="forward",
            # Both sides are sorted on the time key globally, hence within every account.
            check_sortedness=False,
        )
        .group_by("account_id")
        .agg(
            median_hours_to_forward=hours.median(),
            forwarded_within_24h_share=(hours <= _FAST_FORWARD_HOURS).fill_null(value=False).mean(),
        )
    )
