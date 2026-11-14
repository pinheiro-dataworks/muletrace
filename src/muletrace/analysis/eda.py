"""Exploratory analyses behind ``notebooks/01_eda.ipynb``.

Each function answers one question and returns a small table; the notebook only calls these
functions, prints the tables and draws charts. Keeping the logic here means it is tested and
reusable, and the notebook stays a narrative.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

from muletrace.features.account_features import account_age_hours, first_seen, flow_aggregates
from muletrace.features.asof import labels_at, scored_population

_PER_10K = 10_000


def daily_laundering(transactions: pl.LazyFrame) -> pl.DataFrame:
    """How does laundering prevalence move from day to day?"""
    return (
        transactions.group_by(day=pl.col("timestamp").dt.date())
        .agg(transactions=pl.len(), laundering=pl.col("is_laundering").sum())
        .with_columns(laundering_per_10k=pl.col("laundering") / pl.col("transactions") * _PER_10K)
        .sort("day")
        .collect()
    )


def typology_mix(attempts: pl.DataFrame) -> pl.DataFrame:
    """How many attempts of each typology, and how many transactions do they span?"""
    return (
        attempts.group_by(pl.col("typology").cast(pl.String))
        .agg(
            attempts=pl.len(),
            median_transactions=pl.col("n_rows").median(),
            max_transactions=pl.col("n_rows").max(),
        )
        .sort("attempts", descending=True)
    )


def format_mix(transactions: pl.LazyFrame) -> pl.DataFrame:
    """Which payment formats carry laundering, compared with their share of all traffic?"""
    return (
        transactions.group_by(pl.col("payment_format").cast(pl.String))
        .agg(transactions=pl.len(), laundering=pl.col("is_laundering").sum())
        .with_columns(
            share_of_transactions=pl.col("transactions") / pl.col("transactions").sum(),
            share_of_laundering=pl.col("laundering") / pl.col("laundering").sum(),
            laundering_per_10k=pl.col("laundering") / pl.col("transactions") * _PER_10K,
        )
        .sort("laundering", descending=True)
        .collect()
    )


def hour_of_day(transactions: pl.LazyFrame) -> pl.DataFrame:
    """Does laundering happen at different hours from ordinary traffic?"""
    return (
        transactions.filter(~pl.col("is_self_transfer"))
        .group_by(hour=pl.col("timestamp").dt.hour(), laundering="is_laundering")
        .len()
        .with_columns(share=pl.col("len") / pl.col("len").sum().over("laundering"))
        .collect()
        .pivot(on="laundering", index="hour", values="share")
        .rename({"true": "laundering_share", "false": "ordinary_share"}, strict=False)
        .sort("hour")
    )


def snapshot_profile(
    transactions: pl.LazyFrame,
    confirmed: pl.DataFrame,
    as_of: datetime,
    lookback: timedelta,
    horizon: timedelta,
) -> pl.DataFrame:
    """The scored population at ``as_of`` with its label and a few point-in-time features.

    ``already_active`` marks positives whose first illicit inflow happened before ``as_of``:
    with a confirmation delay, part of the target is mules that are active but not yet known.
    """
    population = labels_at(
        scored_population(transactions, confirmed, as_of, lookback), confirmed, as_of, horizon
    )
    flows = flow_aggregates(transactions, as_of, timedelta(hours=24)).collect()
    return (
        population.join(flows, on="account_id", how="left")
        .join(account_age_hours(first_seen(transactions), as_of), on="account_id", how="left")
        .join(confirmed.select("account_id", "became_mule_at"), on="account_id", how="left")
        .with_columns(
            pl.col("^(inflow|outflow|distinct).*$").fill_null(0),
            already_active=pl.col("became_mule_at").is_not_null()
            & (pl.col("became_mule_at") < as_of),
        )
        .drop("became_mule_at")
    )


def compare_groups(profile: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    """Median and mean of each column for mules (label true) and everyone else."""
    return (
        profile.group_by("label")
        .agg(
            pl.len().alias("accounts"),
            *(pl.col(c).median().alias(f"{c}_median") for c in columns),
            *(pl.col(c).mean().alias(f"{c}_mean") for c in columns),
        )
        .sort("label")
    )


def time_to_forward(transactions: pl.LazyFrame, anchors: pl.DataFrame) -> pl.DataFrame:
    """Hours from each anchor time to the account's next outgoing transfer.

    Args:
        transactions: the transactions table.
        anchors: ``account_id`` and ``anchor_at`` (for example the first illicit inflow).

    Returns:
        ``anchors`` plus ``hours_to_forward`` (null when the account never sends again).
    """
    outflows = (
        transactions.filter(~pl.col("is_self_transfer"))
        .select(account_id="sender_id", forwarded_at="timestamp")
        .sort("forwarded_at")
        .collect()
    )
    return (
        anchors.sort("anchor_at")
        .join_asof(
            outflows,
            left_on="anchor_at",
            right_on="forwarded_at",
            by="account_id",
            strategy="forward",
            # Both sides are sorted on the time key globally, hence within every account.
            check_sortedness=False,
        )
        .with_columns(
            hours_to_forward=(pl.col("forwarded_at") - pl.col("anchor_at")).dt.total_minutes() / 60
        )
        .drop("forwarded_at")
        .sort("account_id")
    )


def first_inflows(transactions: pl.LazyFrame, exclude: pl.DataFrame) -> pl.DataFrame:
    """First inflow time of every receiving account not listed in ``exclude``."""
    return (
        transactions.filter(~pl.col("is_self_transfer"))
        .group_by(account_id="receiver_id")
        .agg(anchor_at=pl.col("timestamp").min())
        .collect()
        .join(exclude.select("account_id"), on="account_id", how="anti")
    )


def mule_rate_by_entity_type(accounts: pl.DataFrame, mules: pl.DataFrame) -> pl.DataFrame:
    """Share of accounts of each entity type that became mules."""
    return (
        accounts.select("account_id", entity_type=pl.col("entity_type").cast(pl.String))
        .join(mules.select("account_id", is_mule=pl.lit(value=True)), on="account_id", how="left")
        .group_by("entity_type")
        .agg(accounts=pl.len(), mules=pl.col("is_mule").fill_null(value=False).sum())
        .with_columns(mules_per_10k=pl.col("mules") / pl.col("accounts") * _PER_10K)
        .sort("mules_per_10k", descending=True)
    )
