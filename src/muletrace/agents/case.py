"""The evidence of one case, and the case file the copilot drafts from it.

Evidence is what an analyst would see for an alerted account: its transfers in a window around
the alert (with counterparties, amounts, formats and, for instant transfers, the free-text
description), its risk score and reason codes when available, and a fund-flow trace when a
transfer was disputed. Agents never see raw tables, only this compact bundle.

A case file is structured on purpose: every claim lists the transaction IDs, amounts, dates and
accounts it relies on, so that :mod:`muletrace.validation.fact_checker` can verify every one of
them against the evidence without trusting the model.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # Polars is a batch dependency; the copilot Lambda never builds evidence.
    import polars as pl

ACTIONS: Final = ("hold", "monitor", "close")
TYPOLOGY_LABELS: Final = (
    "BIPARTITE",
    "CYCLE",
    "FAN-IN",
    "FAN-OUT",
    "GATHER-SCATTER",
    "RANDOM",
    "SCATTER-GATHER",
    "STACK",
    "NONE",
)


class EvidenceTransfer(BaseModel):
    """One transfer as the agents see it."""

    model_config = ConfigDict(frozen=True)

    tx_id: int
    timestamp: datetime
    direction: Literal["in", "out"]
    counterparty_id: int
    amount_usd: float
    payment_format: str
    description: str = ""


class CaseEvidence(BaseModel):
    """Everything the copilot may use for one case."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    dataset: str
    account_id: int
    window_start: datetime
    window_end: datetime
    transfers: tuple[EvidenceTransfer, ...]
    risk_probability: float | None = None
    reason_codes: tuple[str, ...] = ()
    trace_summary: dict[str, Any] | None = None

    def transfer(self, tx_id: int) -> EvidenceTransfer | None:
        """The transfer with this ID, if it is part of the evidence."""
        return next((t for t in self.transfers if t.tx_id == tx_id), None)

    def prompt_view(self) -> str:
        """Compact plain-text view used in prompts (one line per transfer)."""
        lines = [
            f"Case {self.case_id}: account {self.account_id}, "
            f"window {self.window_start:%Y-%m-%d %H:%M} to {self.window_end:%Y-%m-%d %H:%M}.",
        ]
        if self.risk_probability is not None:
            reasons = ", ".join(self.reason_codes)
            lines.append(f"Risk probability: {self.risk_probability:.3f}; reasons: {reasons}.")
        lines.append("tx_id | time | direction | counterparty | amount_usd | format | description")
        lines += [
            f"{t.tx_id} | {t.timestamp:%Y-%m-%d %H:%M} | {t.direction} | {t.counterparty_id} | "
            f"{t.amount_usd:.2f} | {t.payment_format} | {t.description}"
            for t in self.transfers
        ]
        return "\n".join(lines)


class Claim(BaseModel):
    """One factual statement, with everything it relies on."""

    text: str = Field(min_length=1)
    tx_ids: list[int] = Field(default_factory=list)
    amounts_usd: list[float] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    account_ids: list[int] = Field(default_factory=list)


class CaseFile(BaseModel):
    """The drafted case file an analyst approves, edits or rejects."""

    case_id: str
    account_id: int
    summary: str
    claims: list[Claim]
    typology: str
    recommended_action: str
    policy_refs: list[str] = Field(default_factory=list)


def build_evidence(
    *,
    case_id: str,
    dataset: str,
    account_id: int,
    transactions: pl.DataFrame,
    descriptions: pl.DataFrame,
    window: tuple[datetime, datetime],
    max_transfers: int,
    must_include: frozenset[int] = frozenset(),
) -> CaseEvidence:
    """Collect the account's transfers in the window (self-transfers excluded).

    ``must_include`` transfers are always kept; the rest are the largest remaining transfers,
    up to ``max_transfers`` in total, then everything is listed in time order.
    """
    import polars as pl  # noqa: PLC0415

    start, end = window
    rows = (
        transactions.filter(
            ((pl.col("sender_id") == account_id) | (pl.col("receiver_id") == account_id))
            & ~pl.col("is_self_transfer")
            & pl.col("timestamp").is_between(start, end)
        )
        .join(descriptions.select("tx_id", "description"), on="tx_id", how="left")
        .with_columns(
            direction=pl.when(pl.col("receiver_id") == account_id)
            .then(pl.lit("in"))
            .otherwise(pl.lit("out")),
            counterparty_id=pl.when(pl.col("receiver_id") == account_id)
            .then(pl.col("sender_id"))
            .otherwise(pl.col("receiver_id")),
            required=pl.col("tx_id").is_in(list(must_include)),
        )
        .sort(["required", "amount_paid_usd"], descending=True)
        .head(max(max_transfers, len(must_include)))
        .sort("timestamp", "tx_id")
    )
    transfers = tuple(
        EvidenceTransfer(
            tx_id=row["tx_id"],
            timestamp=row["timestamp"],
            direction=row["direction"],
            counterparty_id=row["counterparty_id"],
            amount_usd=round(row["amount_paid_usd"], 2),
            payment_format=str(row["payment_format"]),
            description=row["description"] or "",
        )
        for row in rows.iter_rows(named=True)
    )
    return CaseEvidence(
        case_id=case_id,
        dataset=dataset,
        account_id=account_id,
        window_start=start,
        window_end=end,
        transfers=transfers,
    )
