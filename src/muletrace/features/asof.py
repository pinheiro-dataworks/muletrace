"""Point-in-time snapshots: who is scored at time *t*, with what history, and what label.

The single rule of this module: **at as-of time t, only rows with ``timestamp < t`` exist.**
Everything that looks at the future (targets) goes through :func:`labels_at`, which reads
``confirmed_at`` and never ``became_mule_at``.

* :func:`history_before` is the only door to past transactions.
* :func:`scored_population` returns accounts that received a transfer in the lookback window
  and were *not yet confirmed* as mules at *t* (already-confirmed accounts are handled by the
  existing process, not by a score).
* :func:`labels_at` marks accounts confirmed in ``(t, t + horizon]``, optionally truncated at a
  ``known_by`` cut-off so that training labels never use confirmations from after training time.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl


def snapshot_times(first: datetime, last: datetime, step: timedelta) -> list[datetime]:
    """As-of times from ``first`` to ``last`` inclusive, every ``step``."""
    if step <= timedelta(0):
        raise ValueError("step must be positive")
    times: list[datetime] = []
    current = first
    while current <= last:
        times.append(current)
        current += step
    return times


def history_before(
    transactions: pl.LazyFrame, as_of: datetime, window: timedelta | None = None
) -> pl.LazyFrame:
    """Transactions strictly before ``as_of``, optionally limited to the trailing ``window``."""
    condition = pl.col("timestamp") < as_of
    if window is not None:
        condition &= pl.col("timestamp") >= as_of - window
    return transactions.filter(condition)


def scored_population(
    transactions: pl.LazyFrame,
    confirmed: pl.DataFrame,
    as_of: datetime,
    lookback: timedelta,
) -> pl.DataFrame:
    """Accounts scored at ``as_of``: recent receivers that are not confirmed mules yet.

    Returns a frame with ``account_id`` and ``as_of``, sorted by ``account_id``.
    """
    receivers = (
        history_before(transactions, as_of, lookback)
        .filter(~pl.col("is_self_transfer"))
        .select(account_id="receiver_id")
        .unique()
        .collect()
    )
    already_confirmed = confirmed.filter(pl.col("confirmed_at") <= as_of).select("account_id")
    return (
        receivers.join(already_confirmed, on="account_id", how="anti")
        .with_columns(as_of=pl.lit(as_of, dtype=pl.Datetime("ms")))
        .sort("account_id")
    )


def labels_at(
    population: pl.DataFrame,
    confirmed: pl.DataFrame,
    as_of: datetime,
    horizon: timedelta,
    known_by: datetime | None = None,
) -> pl.DataFrame:
    """Add ``label`` (bool): the account is confirmed as a mule in ``(as_of, as_of + horizon]``.

    Args:
        population: output of :func:`scored_population`.
        confirmed: mules with ``account_id`` and ``confirmed_at``.
        as_of: the snapshot time.
        horizon: prediction horizon.
        known_by: if given, confirmations after this time are treated as unknown (label 0).
            Use the training cut-off here so training labels respect label delay.
    """
    end = as_of + horizon
    if known_by is not None:
        end = min(end, known_by)
    positives = confirmed.filter(
        (pl.col("confirmed_at") > as_of) & (pl.col("confirmed_at") <= end)
    ).select("account_id", label=pl.lit(value=True))
    return population.join(positives, on="account_id", how="left").with_columns(
        label=pl.col("label").fill_null(value=False)
    )


def illicit_inflow_in_horizon(
    transactions: pl.LazyFrame, population: pl.DataFrame, as_of: datetime, horizon: timedelta
) -> pl.DataFrame:
    """Add ``illicit_inflow_usd``: laundering inflow received in ``(as_of, as_of + horizon]``.

    This is the simulated value that would reach the account *after* an alert at ``as_of``,
    the quantity behind "value detected". It is an outcome, never a feature.
    """
    future = (
        transactions.filter(
            (pl.col("timestamp") > as_of)
            & (pl.col("timestamp") <= as_of + horizon)
            & pl.col("is_laundering")
            & ~pl.col("is_self_transfer")
        )
        .group_by(account_id="receiver_id")
        .agg(illicit_inflow_usd=pl.col("amount_paid_usd").sum())
        .collect()
    )
    return population.join(future, on="account_id", how="left").with_columns(
        illicit_inflow_usd=pl.col("illicit_inflow_usd").fill_null(0.0)
    )
