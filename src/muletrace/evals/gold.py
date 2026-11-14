"""Gold cases for the copilot, built from AMLworld's patterns file.

A positive case is one laundering attempt seen from the account that receives the most of its
transfers (a mule): its typology, the attempt's transfers touching that account and the action
an analyst should take (hold) are known exactly. The evidence also contains the account's other
transfers in the window, largest first, so the attempt is not handed over on its own.

A negative case is an account that never received laundered money, with at least a few
transfers in the window; its expected typology is ``NONE`` and the expected action is to close
or monitor. Sampling is seeded and stratified by typology.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict

from muletrace.agents.case import CaseEvidence, build_evidence
from muletrace.data.labels import mule_events

WINDOW_PADDING: Final = timedelta(days=1)
NEGATIVE_WINDOW: Final = (datetime(2022, 9, 5), datetime(2022, 9, 8))
NEGATIVE_MIN_TRANSFERS: Final = 5


class GoldCase(BaseModel):
    """One evaluation case and its ground truth."""

    model_config = ConfigDict(frozen=True)

    evidence: CaseEvidence
    typology: str
    expected_actions: tuple[str, ...]
    relevant_tx_ids: tuple[int, ...]

    @property
    def is_positive(self) -> bool:
        """True for a laundering case."""
        return self.typology != "NONE"


def _focal_account(attempt_transfers: pl.DataFrame) -> int:
    counts = (
        attempt_transfers.group_by("receiver_id")
        .len()
        .sort(["len", "receiver_id"], descending=[True, False])
    )
    return int(counts["receiver_id"][0])


def _positive_cases(
    *,
    transactions: pl.DataFrame,
    descriptions: pl.DataFrame,
    linked: pl.DataFrame,
    attempt_ids: list[int],
    dataset: str,
    max_transfers: int,
) -> list[GoldCase]:
    cases = []
    for attempt_id in attempt_ids:
        rows = linked.filter(pl.col("attempt_id") == attempt_id).join(transactions, on="tx_id")
        rows = rows.filter(~pl.col("is_self_transfer"))
        if rows.is_empty():
            continue
        account = _focal_account(rows)
        touching = rows.filter(
            (pl.col("receiver_id") == account) | (pl.col("sender_id") == account)
        )
        first: datetime = rows.select(pl.col("timestamp").min()).item()
        last: datetime = rows.select(pl.col("timestamp").max()).item()
        start, end = first - WINDOW_PADDING, last + WINDOW_PADDING
        relevant = frozenset(touching["tx_id"].to_list())
        evidence = build_evidence(
            case_id=f"{dataset}-attempt-{attempt_id}",
            dataset=dataset,
            account_id=account,
            transactions=transactions,
            descriptions=descriptions,
            window=(start, end),
            max_transfers=max_transfers,
            must_include=relevant,
        )
        cases.append(
            GoldCase(
                evidence=evidence,
                typology=str(rows["typology"][0]),
                expected_actions=("hold",),
                relevant_tx_ids=tuple(sorted(relevant)),
            )
        )
    return cases


def _negative_cases(
    *,
    transactions: pl.DataFrame,
    descriptions: pl.DataFrame,
    n: int,
    seed: int,
    dataset: str,
    max_transfers: int,
) -> list[GoldCase]:
    start, end = NEGATIVE_WINDOW
    mules = mule_events(transactions.lazy())["account_id"]
    window = transactions.filter(
        pl.col("timestamp").is_between(start, end) & ~pl.col("is_self_transfer")
    )
    activity = (
        pl.concat([window.select(account="sender_id"), window.select(account="receiver_id")])
        .group_by("account")
        .len()
        .filter(
            (pl.col("len") >= NEGATIVE_MIN_TRANSFERS) & ~pl.col("account").is_in(mules.to_list())
        )
        .sort("account")
    )
    rng = np.random.default_rng(seed)
    chosen = rng.choice(activity.height, size=min(n, activity.height), replace=False)
    return [
        GoldCase(
            evidence=build_evidence(
                case_id=f"{dataset}-ordinary-{account}",
                dataset=dataset,
                account_id=account,
                transactions=transactions,
                descriptions=descriptions,
                window=(start, end),
                max_transfers=max_transfers,
            ),
            typology="NONE",
            expected_actions=("close", "monitor"),
            relevant_tx_ids=(),
        )
        for account in sorted(int(activity["account"][int(i)]) for i in chosen)
    ]


def build_gold_cases(
    dataset_dir: Path, per_typology: int, negatives: int, seed: int, max_transfers: int = 30
) -> list[GoldCase]:
    """Stratified positive cases from the patterns file plus ordinary accounts."""
    dataset = dataset_dir.name
    transactions = pl.read_parquet(dataset_dir / "transactions.parquet")
    descriptions = pl.read_parquet(
        dataset_dir / "pix_layer" / "pix_transfers.parquet", columns=["tx_id", "description"]
    )
    attempts = pl.read_parquet(dataset_dir / "attempts.parquet")
    linked = pl.read_parquet(dataset_dir / "pattern_transactions.parquet")
    rng = np.random.default_rng(seed)
    attempt_ids: list[int] = []
    for _, group in attempts.sort("attempt_id").group_by("typology", maintain_order=True):
        ids = group["attempt_id"].to_list()
        picked = rng.choice(len(ids), size=min(per_typology, len(ids)), replace=False)
        attempt_ids += sorted(int(ids[int(i)]) for i in picked)
    positives = _positive_cases(
        transactions=transactions,
        descriptions=descriptions,
        linked=linked,
        attempt_ids=attempt_ids,
        dataset=dataset,
        max_transfers=max_transfers,
    )
    negative = _negative_cases(
        transactions=transactions,
        descriptions=descriptions,
        n=negatives,
        seed=seed,
        dataset=dataset,
        max_transfers=max_transfers,
    )
    return positives + negative


def write_gold_cases(cases: list[GoldCase], path: Path) -> None:
    """One JSON object per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [case.model_dump_json() for case in cases]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def read_gold_cases(path: Path) -> list[GoldCase]:
    """Inverse of :func:`write_gold_cases`."""
    return [
        GoldCase.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
