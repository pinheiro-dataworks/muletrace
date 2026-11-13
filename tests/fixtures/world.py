"""A small, seeded AMLworld-format world for end-to-end tests.

Big enough for every pipeline stage to have positives in every snapshot (a few hundred
accounts, ten days, daily laundering chains), small enough to run in seconds. Generated in code,
so no row of the real dataset is ever committed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from tests.fixtures.amlworld import Tx, write_amlworld_files

N_ACCOUNTS = 400
DAYS = 10
ORDINARY_PER_DAY = 500
CHAINS_PER_DAY = 12
START = datetime(2022, 9, 1)
ENTITY_TYPES = ("Corporation", "Partnership", "Sole Proprietorship")


def _account(index: int) -> tuple[str, str]:
    return f"{index % 5 + 1:03d}", f"A{index:04d}"


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y/%m/%d %H:%M")


def generate_world(directory: Path, name: str = "HI-Small", seed: int = 11) -> Path:
    """Write a deterministic world and return its folder."""
    rng = np.random.default_rng(seed)
    rows: list[Tx] = []
    for day in range(DAYS):
        base = START + timedelta(days=day)
        for _ in range(ORDINARY_PER_DAY):
            sender, receiver = rng.choice(N_ACCOUNTS, size=2, replace=False)
            moment = base + timedelta(minutes=int(rng.integers(0, 24 * 60)))
            rows.append(
                Tx(
                    _stamp(moment),
                    *_account(int(sender)),
                    *_account(int(receiver)),
                    round(float(rng.lognormal(6, 1.5)), 2),
                    payment_format=str(rng.choice(["ACH", "Cheque", "Wire"])),
                )
            )
        for _ in range(CHAINS_PER_DAY):
            chain = rng.choice(N_ACCOUNTS, size=3, replace=False)
            moment = base + timedelta(minutes=int(rng.integers(0, 20 * 60)))
            amount = round(float(rng.lognormal(9, 1)), 2)
            rows.extend(
                Tx(
                    _stamp(moment + timedelta(hours=2 * hop)),
                    *_account(int(chain[hop])),
                    *_account(int(chain[hop + 1])),
                    round(amount * (0.9**hop), 2),
                    is_laundering=1,
                )
                for hop in range(2)
            )
    # Cross-currency transfers so every currency has a rate against the US dollar.
    rows += [
        Tx(
            "2022/09/01 05:00",
            *_account(1),
            *_account(2),
            100.0,
            received_amount=85.0,
            received_currency="Euro",
        ),
        Tx(
            "2022/09/01 06:00",
            *_account(3),
            *_account(4),
            564.65,
            currency="Brazil Real",
            received_amount=100.0,
            received_currency="US Dollar",
        ),
    ]
    accounts = tuple(
        (f"Bank #{i % 5 + 1}", str(i % 5 + 1), f"A{i:04d}", f"E{i}", f"{ENTITY_TYPES[i % 3]} #{i}")
        for i in range(N_ACCOUNTS)
    )
    return write_amlworld_files(directory, name, tuple(rows), accounts, patterns="")
