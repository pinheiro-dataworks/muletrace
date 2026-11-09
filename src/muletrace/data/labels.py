"""Mule events and their delayed confirmation.

A receiving account *becomes a mule* at its first laundering inflow, self-transfers excluded.
In practice nobody knows this at that moment: the account is *confirmed* later, when a dispute,
a DICT fraud marking or an investigation closes. The gap is the confirmation delay.

Two timestamps therefore exist for every mule, and code must never confuse them:

* ``became_mule_at`` is ground truth from the simulator and is only used to build targets;
* ``confirmed_at`` is the first moment the label is *known*, and is the only one that features,
  neighbour labels and training-label cut-offs may use.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl
from pydantic import Field

from muletrace.config import StrictModel


class LabelConfig(StrictModel):
    """Target definition, read from ``configs/labels.yaml``."""

    confirmation_delay_hours: int = Field(ge=0)
    horizon_hours: int = Field(gt=0)
    population_lookback_days: int = Field(gt=0)

    @property
    def confirmation_delay(self) -> timedelta:
        """Time between becoming a mule and being confirmed as one."""
        return timedelta(hours=self.confirmation_delay_hours)

    @property
    def horizon(self) -> timedelta:
        """Prediction horizon after the as-of time."""
        return timedelta(hours=self.horizon_hours)

    @property
    def population_lookback(self) -> timedelta:
        """Activity window that defines the scored population."""
        return timedelta(days=self.population_lookback_days)


def mule_events(transactions: pl.LazyFrame) -> pl.DataFrame:
    """Return one row per mule: ``account_id``, ``became_mule_at``, ``first_illicit_tx_id``.

    Ties on the first timestamp are broken by ``tx_id`` so the result is deterministic.
    """
    return (
        transactions.filter(pl.col("is_laundering") & ~pl.col("is_self_transfer"))
        .sort("timestamp", "tx_id")
        .group_by("receiver_id")
        .agg(
            became_mule_at=pl.col("timestamp").first(),
            first_illicit_tx_id=pl.col("tx_id").first(),
        )
        .rename({"receiver_id": "account_id"})
        .sort("account_id")
        .collect()
    )


def confirmations(events: pl.DataFrame, delay: timedelta) -> pl.DataFrame:
    """Add ``confirmed_at = became_mule_at + delay`` to the mule events."""
    if delay < timedelta(0):
        raise ValueError("confirmation delay cannot be negative")
    return events.with_columns(confirmed_at=pl.col("became_mule_at") + pl.lit(delay))
