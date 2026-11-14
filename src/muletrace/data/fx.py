"""Exchange rates inferred from AMLworld's own cross-currency transfers.

AMLworld amounts come in fifteen currencies. Features need one unit of account, and the Pix
layer needs Brazilian reals. Rather than importing market rates from an outside source (which
would mix a real-world reference with a synthetic world), the rates are read from the data:
when a transfer is paid in one currency and received in another, ``amount_received /
amount_paid`` is the simulator's exchange rate. In HI-Small and LI-Small these ratios are
almost constant per currency pair, so the median is a faithful summary.

The rate table is a static property of the synthetic world, not a time series, so using all
rows to estimate it does not leak information across time.
"""

from __future__ import annotations

from typing import Final

import polars as pl

USD: Final = "US Dollar"
BRL: Final = "Brazil Real"


class MissingRateError(ValueError):
    """Raised when a currency has no cross-currency transfer against the US dollar."""


def usd_rate_table(raw_transactions: pl.LazyFrame) -> pl.DataFrame:
    """Return units of each currency per US dollar, with the evidence behind each rate.

    Columns: ``currency``, ``units_per_usd`` (median ratio), ``n_observations`` and
    ``relative_iqr`` (interquartile range divided by the median, a stability check).
    """
    paid_in_usd = raw_transactions.filter(
        (pl.col("payment_currency") == USD) & (pl.col("receiving_currency") != USD)
    ).select(
        currency=pl.col("receiving_currency").cast(pl.String),
        ratio=pl.col("amount_received") / pl.col("amount_paid"),
    )
    received_in_usd = raw_transactions.filter(
        (pl.col("receiving_currency") == USD) & (pl.col("payment_currency") != USD)
    ).select(
        currency=pl.col("payment_currency").cast(pl.String),
        ratio=pl.col("amount_paid") / pl.col("amount_received"),
    )
    table = (
        pl.concat([paid_in_usd, received_in_usd])
        .group_by("currency")
        .agg(
            units_per_usd=pl.col("ratio").median(),
            n_observations=pl.len(),
            relative_iqr=(pl.col("ratio").quantile(0.75) - pl.col("ratio").quantile(0.25))
            / pl.col("ratio").median(),
        )
        .collect()
    )
    usd_row = pl.DataFrame(
        {"currency": [USD], "units_per_usd": [1.0], "n_observations": [0], "relative_iqr": [0.0]},
        schema=table.schema,
    )
    return pl.concat([table, usd_row]).sort("currency")


def derive_usd_rates(raw_transactions: pl.LazyFrame) -> dict[str, float]:
    """Return ``{currency: units per US dollar}`` for every currency in the data.

    Raises:
        MissingRateError: if a currency appears in the data but never against the US dollar.
    """
    table = usd_rate_table(raw_transactions)
    rates = dict(zip(table["currency"].to_list(), table["units_per_usd"].to_list(), strict=True))
    present = (
        pl.concat(
            [
                raw_transactions.select(currency=pl.col("payment_currency").cast(pl.String)),
                raw_transactions.select(currency=pl.col("receiving_currency").cast(pl.String)),
            ]
        )
        .unique()
        .collect()["currency"]
        .to_list()
    )
    missing = sorted(set(present) - set(rates))
    if missing:
        msg = f"No cross-currency transfer against {USD} for: {', '.join(missing)}"
        raise MissingRateError(msg)
    return rates


def add_usd_amounts(transactions: pl.LazyFrame, rates: dict[str, float]) -> pl.LazyFrame:
    """Add ``amount_paid_usd``: the paid amount converted with the inferred rate table."""
    return transactions.with_columns(
        amount_paid_usd=pl.col("amount_paid")
        / pl.col("payment_currency").cast(pl.String).replace_strict(rates, return_dtype=pl.Float64)
    )
