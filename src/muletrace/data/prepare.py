"""Ingestion stage: raw AMLworld files in, validated Parquet tables out.

Outputs, per dataset, under ``<data_dir>/processed/<dataset>/``:

* ``transactions.parquet`` sorted by ``(timestamp, tx_id)``;
* ``accounts.parquet`` with the compact ``account_id`` mapping;
* ``attempts.parquet`` and ``pattern_transactions.parquet`` from the patterns file;
* ``usd_rates.parquet``, the exchange-rate table inferred from the data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from muletrace.data import contracts
from muletrace.data.amlworld_loader import (
    RawDataset,
    build_account_table,
    build_transaction_table,
    read_raw_accounts,
    scan_raw_transactions,
)
from muletrace.data.fx import usd_rate_table
from muletrace.data.patterns import attempts_table, link_pattern_transactions, read_patterns

logger = logging.getLogger(__name__)

PARQUET_COMPRESSION: Final = "zstd"


@dataclass(frozen=True)
class PreparedDataset:
    """Paths and headline counts of one prepared dataset."""

    name: str
    output_dir: Path
    n_transactions: int
    n_laundering: int
    n_accounts: int
    n_attempts: int
    n_pattern_rows_unmatched: int

    @property
    def transactions_path(self) -> Path:
        """Typed transactions table."""
        return self.output_dir / "transactions.parquet"


def processed_paths(processed_dir: Path, dataset: str) -> dict[str, Path]:
    """Return the expected output files of :func:`prepare_dataset` for ``dataset``."""
    base = processed_dir / dataset
    names = ("transactions", "accounts", "attempts", "pattern_transactions", "usd_rates")
    return {name: base / f"{name}.parquet" for name in names}


def prepare_dataset(raw: RawDataset, processed_dir: Path) -> PreparedDataset:
    """Run the ingestion stage for one dataset and write its Parquet outputs."""
    paths = processed_paths(processed_dir, raw.name)
    output_dir = paths["transactions"].parent
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_transactions = scan_raw_transactions(raw.transactions_csv)
    accounts = contracts.validate(
        contracts.ACCOUNTS,
        build_account_table(raw_transactions, read_raw_accounts(raw.accounts_csv)),
    )
    transactions = contracts.validate(
        contracts.TRANSACTIONS, build_transaction_table(raw_transactions, accounts)
    )

    attempts = read_patterns(raw.patterns_txt)
    linked = link_pattern_transactions(attempts, raw_transactions)
    unmatched = linked.filter(pl.col("tx_id").is_null()).height
    if unmatched:
        logger.warning("%s: %d pattern rows have no matching transaction", raw.name, unmatched)
    pattern_transactions = contracts.validate(
        contracts.PATTERN_TRANSACTIONS, linked.drop_nulls("tx_id")
    )

    transactions.write_parquet(paths["transactions"], compression=PARQUET_COMPRESSION)
    accounts.write_parquet(paths["accounts"], compression=PARQUET_COMPRESSION)
    attempts_table(attempts).write_parquet(paths["attempts"], compression=PARQUET_COMPRESSION)
    pattern_transactions.write_parquet(
        paths["pattern_transactions"], compression=PARQUET_COMPRESSION
    )
    usd_rate_table(raw_transactions).write_parquet(
        paths["usd_rates"], compression=PARQUET_COMPRESSION
    )

    prepared = PreparedDataset(
        name=raw.name,
        output_dir=output_dir,
        n_transactions=transactions.height,
        n_laundering=int(transactions["is_laundering"].sum()),
        n_accounts=accounts.height,
        n_attempts=len(attempts),
        n_pattern_rows_unmatched=unmatched,
    )
    logger.info("%s prepared: %s", raw.name, prepared)
    return prepared
