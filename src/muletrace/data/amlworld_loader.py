"""Load IBM AMLworld CSV files into typed tables with stable identifiers.

AMLworld has no transaction identifier and repeats the column name ``Account`` for sender and
receiver. This module fixes both problems once, at the boundary:

* ``tx_id`` is the zero-based row number in the source CSV (header excluded). Because the
  source files are pinned by SHA-256 in ``data/MANIFEST.yaml``, the identifier is reproducible
  and any transaction cited by the copilot can be traced back to one line of the original file.
* Accounts are identified by ``(bank_id, account_number)``. Bank codes are zero-padded strings
  in the transactions file (``"010"``) and plain integers in the accounts file (``10``), so both
  are normalised to integers before joining.
* Each account receives a compact ``account_id`` (``UInt32``), assigned in lexicographic order of
  ``account_key`` so that the mapping does not depend on file order.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from muletrace.data.fx import add_usd_amounts, derive_usd_rates

DATASETS: Final = ("HI-Small", "LI-Small")

CURRENCIES: Final = (
    "Australian Dollar",
    "Bitcoin",
    "Brazil Real",
    "Canadian Dollar",
    "Euro",
    "Mexican Peso",
    "Ruble",
    "Rupee",
    "Saudi Riyal",
    "Shekel",
    "Swiss Franc",
    "UK Pound",
    "US Dollar",
    "Yen",
    "Yuan",
)
PAYMENT_FORMATS: Final = (
    "ACH",
    "Bitcoin",
    "Cash",
    "Cheque",
    "Credit Card",
    "Reinvestment",
    "Wire",
)
ENTITY_TYPES: Final = (
    "Corporation",
    "Country",
    "Direct",
    "Individual",
    "Partnership",
    "Sole Proprietorship",
    "Unknown",
)

CurrencyDtype: Final = pl.Enum(CURRENCIES)
PaymentFormatDtype: Final = pl.Enum(PAYMENT_FORMATS)
EntityTypeDtype: Final = pl.Enum(ENTITY_TYPES)

TRANSACTIONS_HEADER: Final = (
    "Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,"
    "Amount Paid,Payment Currency,Payment Format,Is Laundering"
)
ACCOUNTS_HEADER: Final = "Bank Name,Bank ID,Account Number,Entity ID,Entity Name"

RAW_TRANSACTION_SCHEMA: Final = pl.Schema(
    {
        "timestamp": pl.String,
        "from_bank": pl.String,
        "from_account": pl.String,
        "to_bank": pl.String,
        "to_account": pl.String,
        "amount_received": pl.Float64,
        "receiving_currency": pl.String,
        "amount_paid": pl.Float64,
        "payment_currency": pl.String,
        "payment_format": pl.String,
        "is_laundering": pl.Int8,
    }
)
RAW_ACCOUNT_SCHEMA: Final = pl.Schema(
    {
        "bank_name": pl.String,
        "bank_id": pl.String,
        "account_number": pl.String,
        "entity_id": pl.String,
        "entity_name": pl.String,
    }
)
TIMESTAMP_FORMAT: Final = "%Y/%m/%d %H:%M"


class SourceFormatError(ValueError):
    """Raised when a raw file does not have the layout this loader was written for."""


@dataclass(frozen=True)
class RawDataset:
    """The three files Kaggle ships for one AMLworld variant."""

    name: str
    raw_dir: Path

    @property
    def transactions_csv(self) -> Path:
        """Transactions file, for example ``HI-Small_Trans.csv``."""
        return self.raw_dir / f"{self.name}_Trans.csv"

    @property
    def accounts_csv(self) -> Path:
        """Accounts file, for example ``HI-Small_accounts.csv``."""
        return self.raw_dir / f"{self.name}_accounts.csv"

    @property
    def patterns_txt(self) -> Path:
        """Laundering patterns file, for example ``HI-Small_Patterns.txt``."""
        return self.raw_dir / f"{self.name}_Patterns.txt"

    @property
    def files(self) -> tuple[Path, Path, Path]:
        """All source files, in a fixed order."""
        return (self.transactions_csv, self.accounts_csv, self.patterns_txt)


def _check_header(path: Path, expected: str) -> None:
    with path.open(encoding="utf-8") as handle:
        header = handle.readline().strip()
    if header != expected:
        msg = f"{path.name}: unexpected header {header!r}, expected {expected!r}"
        raise SourceFormatError(msg)


def scan_raw_transactions(path: Path) -> pl.LazyFrame:
    """Lazily read a transactions CSV with explicit column names and types.

    The header is checked first, then skipped, because the source repeats ``Account``.
    ``tx_id`` is attached here, before any filtering or sorting, so it always equals the source
    row number.
    """
    _check_header(path, TRANSACTIONS_HEADER)
    return pl.scan_csv(
        path, has_header=False, skip_rows=1, schema=RAW_TRANSACTION_SCHEMA
    ).with_row_index("tx_id")


def read_raw_accounts(path: Path) -> pl.DataFrame:
    """Read an accounts CSV with explicit column names and types."""
    _check_header(path, ACCOUNTS_HEADER)
    return pl.read_csv(path, has_header=False, skip_rows=1, schema=RAW_ACCOUNT_SCHEMA)


def _account_key(bank: pl.Expr, account: pl.Expr) -> pl.Expr:
    return pl.concat_str([bank.cast(pl.UInt32).cast(pl.String), account], separator=":")


def build_account_table(raw_transactions: pl.LazyFrame, raw_accounts: pl.DataFrame) -> pl.DataFrame:
    """Return one row per account seen in either file, with a compact ``account_id``.

    The accounts file has a handful of repeated ``(bank, account)`` rows; the first occurrence
    is kept. Accounts present only in transactions get entity type ``Unknown``.
    """
    seen_in_transactions = pl.concat(
        [
            raw_transactions.select(
                account_key=_account_key(pl.col("from_bank"), pl.col("from_account"))
            ),
            raw_transactions.select(
                account_key=_account_key(pl.col("to_bank"), pl.col("to_account"))
            ),
        ]
    ).unique()
    reference = (
        raw_accounts.lazy()
        .with_columns(
            account_key=_account_key(pl.col("bank_id"), pl.col("account_number")),
            entity_type=pl.col("entity_name").str.replace(r"\s*#\d+$", ""),
        )
        .unique("account_key", keep="first", maintain_order=True)
        .select("account_key", "bank_name", "entity_id", "entity_type")
    )
    all_keys = pl.concat([seen_in_transactions, reference.select("account_key")]).unique()
    return (
        all_keys.join(reference, on="account_key", how="left")
        .sort("account_key")
        .with_row_index("account_id")
        .with_columns(
            bank_id=pl.col("account_key").str.split(":").list.first().cast(pl.UInt32),
            account_number=pl.col("account_key").str.split(":").list.last(),
            entity_type=pl.col("entity_type").fill_null("Unknown").cast(EntityTypeDtype),
        )
        .select(
            "account_id",
            "account_key",
            "bank_id",
            "account_number",
            "bank_name",
            "entity_id",
            "entity_type",
        )
        .collect()
    )


def build_transaction_table(raw_transactions: pl.LazyFrame, accounts: pl.DataFrame) -> pl.DataFrame:
    """Return the typed transactions table, sorted by ``(timestamp, tx_id)``.

    Amounts stay ``Float64``: AMLworld amounts reach 1e12 and a ``Float32`` would lose cents,
    which the fact checker compares exactly. Currencies and payment formats become enums, and
    account identifiers become ``UInt32``, which keeps the table around a third of the size of
    the string version.
    """
    key_to_id = accounts.lazy().select("account_key", "account_id")
    rates = derive_usd_rates(raw_transactions)
    typed = (
        raw_transactions.with_columns(
            timestamp=pl.col("timestamp").str.strptime(pl.Datetime("ms"), TIMESTAMP_FORMAT),
            sender_key=_account_key(pl.col("from_bank"), pl.col("from_account")),
            receiver_key=_account_key(pl.col("to_bank"), pl.col("to_account")),
            payment_currency=pl.col("payment_currency").cast(CurrencyDtype),
            receiving_currency=pl.col("receiving_currency").cast(CurrencyDtype),
            payment_format=pl.col("payment_format").cast(PaymentFormatDtype),
            is_laundering=pl.col("is_laundering").cast(pl.Boolean),
        )
        .join(
            key_to_id.rename({"account_key": "sender_key", "account_id": "sender_id"}),
            on="sender_key",
        )
        .join(
            key_to_id.rename({"account_key": "receiver_key", "account_id": "receiver_id"}),
            on="receiver_key",
        )
        .with_columns(is_self_transfer=pl.col("sender_id") == pl.col("receiver_id"))
    )
    return (
        add_usd_amounts(typed, rates)
        .select(
            "tx_id",
            "timestamp",
            "sender_id",
            "receiver_id",
            "amount_paid",
            "payment_currency",
            "amount_received",
            "receiving_currency",
            "amount_paid_usd",
            "payment_format",
            "is_self_transfer",
            "is_laundering",
        )
        .sort("timestamp", "tx_id")
        .collect()
    )
