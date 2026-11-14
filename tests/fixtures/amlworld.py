"""Tiny AMLworld-format files generated in code.

The test suite never ships rows from the real dataset. These helpers write files that follow
the published layout (header, zero-padded bank codes, repeated ``Account`` column, patterns
blocks) so the loader is exercised on the same quirks as the real files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from muletrace.data.amlworld_loader import ACCOUNTS_HEADER, TRANSACTIONS_HEADER


@dataclass(frozen=True)
class Tx:
    """One transactions-file row with readable defaults."""

    timestamp: str
    from_bank: str
    from_account: str
    to_bank: str
    to_account: str
    amount: float
    currency: str = "US Dollar"
    payment_format: str = "ACH"
    is_laundering: int = 0
    received_amount: float | None = None
    received_currency: str | None = None

    def csv(self) -> str:
        received = self.amount if self.received_amount is None else self.received_amount
        received_currency = self.received_currency or self.currency
        return (
            f"{self.timestamp},{self.from_bank},{self.from_account},{self.to_bank},"
            f"{self.to_account},{received:.2f},{received_currency},{self.amount:.2f},"
            f"{self.currency},{self.payment_format},{self.is_laundering}"
        )


DEFAULT_TRANSACTIONS = (
    Tx("2022/09/01 00:20", "010", "A1", "010", "A1", 100.0, payment_format="Reinvestment"),
    Tx("2022/09/01 00:05", "010", "A1", "0020", "B1", 50.0),
    Tx("2022/09/01 01:00", "0020", "B1", "003", "C1", 45.0, is_laundering=1),
    Tx("2022/09/01 01:00", "0020", "B1", "003", "C1", 45.0, is_laundering=1),
    Tx(
        "2022/09/01 02:00",
        "003",
        "C1",
        "010",
        "A1",
        10.0,
        received_amount=8.5,
        received_currency="Euro",
    ),
    Tx(
        "2022/09/01 03:00",
        "0020",
        "B1",
        "003",
        "C1",
        564.65,
        currency="Brazil Real",
        received_amount=100.0,
        received_currency="US Dollar",
    ),
    Tx("2022/09/02 09:00", "003", "C1", "0040", "D9", 30.0, is_laundering=1),
)
DEFAULT_ACCOUNTS = (
    ("Alpha Bank #1", "10", "A1", "E1", "Corporation #1"),
    ("Beta Bank #2", "20", "B1", "E2", "Individual #7"),
    ("Gamma Bank #3", "3", "C1", "E3", "Sole Proprietorship #3"),
    ("Gamma Bank #3", "3", "C1", "E3", "Sole Proprietorship #3"),
)
DEFAULT_PATTERNS = """BEGIN LAUNDERING ATTEMPT - STACK
{row_a}
{row_b}
END LAUNDERING ATTEMPT - STACK

BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 1-degree Fan-Out
{row_c}
END LAUNDERING ATTEMPT - FAN-OUT
"""


def write_amlworld_files(
    directory: Path,
    name: str = "HI-Small",
    transactions: tuple[Tx, ...] = DEFAULT_TRANSACTIONS,
    accounts: tuple[tuple[str, str, str, str, str], ...] = DEFAULT_ACCOUNTS,
    patterns: str | None = None,
) -> Path:
    """Write ``<name>_Trans.csv``, ``<name>_accounts.csv`` and ``<name>_Patterns.txt``."""
    directory.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(tx.csv() for tx in transactions)
    (directory / f"{name}_Trans.csv").write_text(
        f"{TRANSACTIONS_HEADER}\n{rows}\n", encoding="utf-8"
    )
    account_rows = "\n".join(",".join(row) for row in accounts)
    (directory / f"{name}_accounts.csv").write_text(
        f"{ACCOUNTS_HEADER}\n{account_rows}\n", encoding="utf-8"
    )
    if patterns is None:
        patterns = DEFAULT_PATTERNS.format(
            row_a=transactions[2].csv(), row_b=transactions[3].csv(), row_c=transactions[6].csv()
        )
    (directory / f"{name}_Patterns.txt").write_text(patterns, encoding="utf-8")
    return directory
