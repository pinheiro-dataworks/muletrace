from pathlib import Path

import polars as pl
import pytest

from muletrace.data.amlworld_loader import (
    RawDataset,
    SourceFormatError,
    build_account_table,
    build_transaction_table,
    read_raw_accounts,
    scan_raw_transactions,
)
from muletrace.data.fx import MissingRateError, derive_usd_rates
from tests.fixtures.amlworld import DEFAULT_TRANSACTIONS, Tx, write_amlworld_files


@pytest.fixture
def raw(tmp_path: Path) -> RawDataset:
    return RawDataset("HI-Small", write_amlworld_files(tmp_path / "raw"))


@pytest.fixture
def tables(raw: RawDataset) -> tuple[pl.DataFrame, pl.DataFrame]:
    scanned = scan_raw_transactions(raw.transactions_csv)
    accounts = build_account_table(scanned, read_raw_accounts(raw.accounts_csv))
    return accounts, build_transaction_table(scanned, accounts)


def test_tx_id_is_the_source_row_number(raw: RawDataset) -> None:
    scanned = scan_raw_transactions(raw.transactions_csv).collect()
    assert scanned["tx_id"].to_list() == list(range(len(DEFAULT_TRANSACTIONS)))
    assert scanned["timestamp"][1] == DEFAULT_TRANSACTIONS[1].timestamp


def test_unexpected_header_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("Timestamp,From,To\n", encoding="utf-8")
    with pytest.raises(SourceFormatError, match="unexpected header"):
        scan_raw_transactions(path)


def test_zero_padded_bank_codes_join_the_accounts_file(
    tables: tuple[pl.DataFrame, pl.DataFrame],
) -> None:
    accounts, _ = tables
    by_key = {row["account_key"]: row for row in accounts.iter_rows(named=True)}
    assert by_key["20:B1"]["entity_type"] == "Individual"
    assert by_key["3:C1"]["entity_type"] == "Sole Proprietorship"
    assert by_key["40:D9"]["entity_type"] == "Unknown"
    assert accounts.height == 4  # the repeated C1 row is kept once


def test_account_ids_follow_key_order(tables: tuple[pl.DataFrame, pl.DataFrame]) -> None:
    accounts, _ = tables
    assert accounts["account_key"].to_list() == sorted(accounts["account_key"].to_list())
    assert accounts["account_id"].to_list() == list(range(accounts.height))


def test_transactions_are_sorted_and_typed(tables: tuple[pl.DataFrame, pl.DataFrame]) -> None:
    _, transactions = tables
    assert transactions["timestamp"].is_sorted()
    assert transactions["tx_id"].to_list()[:2] == [1, 0]  # 00:05 comes before 00:20
    self_transfer = transactions.filter(pl.col("tx_id") == 0)
    assert self_transfer["is_self_transfer"].item() is True


def test_usd_amounts_use_inferred_rates(tables: tuple[pl.DataFrame, pl.DataFrame]) -> None:
    _, transactions = tables
    brl_row = transactions.filter(pl.col("tx_id") == 5)
    assert brl_row["amount_paid_usd"].item() == pytest.approx(100.0)


def test_rates_require_a_usd_counterpart(tmp_path: Path) -> None:
    rows = (Tx("2022/09/01 00:00", "001", "A", "002", "B", 10.0, currency="Yen"),)
    raw = RawDataset("HI-Small", write_amlworld_files(tmp_path, transactions=rows, patterns=""))
    with pytest.raises(MissingRateError, match="Yen"):
        derive_usd_rates(scan_raw_transactions(raw.transactions_csv))


def test_derived_rates_are_medians_per_currency(raw: RawDataset) -> None:
    rates = derive_usd_rates(scan_raw_transactions(raw.transactions_csv))
    assert rates["US Dollar"] == 1.0
    assert rates["Euro"] == pytest.approx(0.85)
    assert rates["Brazil Real"] == pytest.approx(5.6465)
