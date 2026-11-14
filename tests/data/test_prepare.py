from pathlib import Path

import pandera.errors
import polars as pl
import pytest

from muletrace.data import contracts
from muletrace.data.amlworld_loader import RawDataset
from muletrace.data.patterns import TypologyDtype
from muletrace.data.prepare import prepare_dataset, processed_paths
from tests.fixtures.amlworld import DEFAULT_TRANSACTIONS, Tx, write_amlworld_files


@pytest.fixture
def raw(tmp_path: Path) -> RawDataset:
    return RawDataset("HI-Small", write_amlworld_files(tmp_path / "raw"))


def test_prepare_writes_every_output(raw: RawDataset, tmp_path: Path) -> None:
    prepared = prepare_dataset(raw, tmp_path / "processed")
    paths = processed_paths(tmp_path / "processed", "HI-Small")
    assert all(path.is_file() for path in paths.values())
    assert prepared.n_transactions == len(DEFAULT_TRANSACTIONS)
    assert prepared.n_laundering == 3
    assert prepared.n_attempts == 2
    assert prepared.n_pattern_rows_unmatched == 0
    assert prepared.transactions_path == paths["transactions"]
    contracts.validate(contracts.TRANSACTIONS, pl.read_parquet(paths["transactions"]))
    linked = pl.read_parquet(paths["pattern_transactions"])
    assert linked.filter(pl.col("attempt_id") == 0)["tx_id"].to_list() == [2, 3]


def test_prepare_reports_unmatched_pattern_rows(tmp_path: Path) -> None:
    ghost = Tx("2022/09/09 09:09", "009", "Z9", "008", "Y8", 1.0, is_laundering=1)
    patterns = (
        "BEGIN LAUNDERING ATTEMPT - CYCLE:  Max 2 hops\n"
        f"{ghost.csv()}\n"
        "END LAUNDERING ATTEMPT - CYCLE\n"
    )
    raw = RawDataset("HI-Small", write_amlworld_files(tmp_path / "raw", patterns=patterns))
    prepared = prepare_dataset(raw, tmp_path / "processed")
    assert prepared.n_pattern_rows_unmatched == 1


def test_pattern_contract_rejects_duplicate_links() -> None:
    frame = pl.DataFrame(
        {"attempt_id": [0, 0], "typology": ["CYCLE", "CYCLE"], "tx_id": [5, 5]},
        schema={
            "attempt_id": pl.UInt32,
            "typology": TypologyDtype,
            "tx_id": pl.UInt32,
        },
    )
    with pytest.raises(pandera.errors.SchemaErrors):
        contracts.validate(contracts.PATTERN_TRANSACTIONS, frame)
