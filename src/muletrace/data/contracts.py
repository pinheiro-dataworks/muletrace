"""Data contracts checked at every stage boundary.

The schemas are strict: an unexpected column, a wrong dtype, a duplicated identifier or an
out-of-range value fails the stage instead of flowing silently into features. Validation runs
in lazy mode so one run reports every violation, not only the first.
"""

from __future__ import annotations

from typing import Final

import pandera.polars as pa
import polars as pl

from muletrace.data.amlworld_loader import CurrencyDtype, EntityTypeDtype, PaymentFormatDtype
from muletrace.data.patterns import TypologyDtype

TRANSACTIONS: Final = pa.DataFrameSchema(
    {
        "tx_id": pa.Column(pl.UInt32, unique=True),
        "timestamp": pa.Column(pl.Datetime("ms")),
        "sender_id": pa.Column(pl.UInt32),
        "receiver_id": pa.Column(pl.UInt32),
        "amount_paid": pa.Column(pl.Float64, pa.Check.gt(0)),
        "payment_currency": pa.Column(CurrencyDtype),
        "amount_received": pa.Column(pl.Float64, pa.Check.gt(0)),
        "receiving_currency": pa.Column(CurrencyDtype),
        "amount_paid_usd": pa.Column(pl.Float64, pa.Check.gt(0)),
        "payment_format": pa.Column(PaymentFormatDtype),
        "is_self_transfer": pa.Column(pl.Boolean),
        "is_laundering": pa.Column(pl.Boolean),
    },
    strict=True,
    name="transactions",
)

ACCOUNTS: Final = pa.DataFrameSchema(
    {
        "account_id": pa.Column(pl.UInt32, unique=True),
        "account_key": pa.Column(pl.String, unique=True),
        "bank_id": pa.Column(pl.UInt32),
        "account_number": pa.Column(pl.String, pa.Check.str_length(min_value=1)),
        "bank_name": pa.Column(pl.String, nullable=True),
        "entity_id": pa.Column(pl.String, nullable=True),
        "entity_type": pa.Column(EntityTypeDtype),
    },
    strict=True,
    name="accounts",
)

PATTERN_TRANSACTIONS: Final = pa.DataFrameSchema(
    {
        "attempt_id": pa.Column(pl.UInt32),
        "typology": pa.Column(TypologyDtype),
        "tx_id": pa.Column(pl.UInt32),
    },
    strict=True,
    unique=["attempt_id", "tx_id"],
    name="pattern_transactions",
)


def validate(schema: pa.DataFrameSchema, frame: pl.DataFrame) -> pl.DataFrame:
    """Validate ``frame`` against ``schema``, collecting every failure before raising."""
    validated: pl.DataFrame = schema.validate(frame, lazy=True)
    return validated
