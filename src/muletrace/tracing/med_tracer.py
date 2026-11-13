"""Fund-flow tracer for a disputed transfer, inspired by MED 2.0.

Given a disputed transfer, the tracer rebuilds where the money went next and estimates how much
of it could still be sitting in each account. It is *inspired by* the tracing step of the Pix
special return mechanism (MED 2.0) and uses the four parameters the BCB names for it —
maximum hops, hop window, minimum transaction amount and maximum transactions — with values
that are assumptions (``configs/tracer.yaml``).

**Allocation rule.** Account balances are not observable, so the tracer assumes that an account
spends its tainted money first, oldest first (first in, first out). This is the pessimistic
case for recovery: it moves as much tainted money onward as the transfers allow. Each tainted
amount is a *lot* with an arrival time and a hop number:

* an outflow at time τ consumes lots that arrived before τ and no more than the hop window
  earlier, oldest first, up to the outflow's amount;
* what it consumes travels to the receiver as a new lot with hop + 1, unless the outflow cannot
  be followed (hop limit reached, amount below the minimum, transaction cap reached), in which
  case it is counted as having **left the trace**;
* whatever is not consumed by the end of the analysis window stays in the account and is the
  **recoverable estimate** for that account.

**Invariants** (tested): the disputed amount equals the recoverable estimates plus the amount
that left the trace; no hop carries more tainted money than the transfer's amount; every hop
happens strictly after the disputed transfer.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import polars as pl
from pydantic import Field

from muletrace.config import StrictModel

_TOLERANCE = 1e-6


class TracerConfig(StrictModel):
    """Tracing parameters, read from ``configs/tracer.yaml``."""

    max_hops: int = Field(gt=0)
    hop_window_hours: float = Field(gt=0)
    min_transaction_usd: float = Field(ge=0)
    max_transactions: int = Field(gt=0)

    @property
    def hop_window(self) -> timedelta:
        """Longest time tainted money may wait in an account and still be followed."""
        return timedelta(hours=self.hop_window_hours)


@dataclass
class _Lot:
    amount: float
    arrived_at: datetime
    hop: int


@dataclass
class TraceResult:
    """Outcome of one trace, in US dollars."""

    disputed_tx_id: int
    disputed_usd: float
    hops: pl.DataFrame
    nodes: pl.DataFrame
    left_trace_usd: float
    followed_transactions: int
    notes: list[str] = field(default_factory=list)

    @property
    def recoverable_usd(self) -> float:
        """Sum of the recoverable estimates over every traced account."""
        return float(self.nodes["recoverable_usd"].sum()) if self.nodes.height else 0.0

    def summary(self) -> dict[str, Any]:
        """Headline figures for a case file."""
        return {
            "disputed_tx_id": self.disputed_tx_id,
            "disputed_usd": round(self.disputed_usd, 2),
            "recoverable_usd": round(self.recoverable_usd, 2),
            "left_trace_usd": round(self.left_trace_usd, 2),
            "accounts_reached": self.nodes.height,
            "hops_followed": self.hops.height,
            "max_hop_reached": int(self.hops.select(pl.col("hop").max()).item())
            if self.hops.height
            else 0,
            "notes": list(self.notes),
        }


def _candidate_outflows(
    transactions: pl.LazyFrame, start: int, after: datetime, until: datetime, max_hops: int
) -> pl.DataFrame:
    """Outflows of every account reachable from ``start`` within the hop limit and time range.

    Reachability ignores amounts, so this is a superset of what the allocation will follow;
    it keeps the in-memory sweep small.
    """
    window = transactions.filter(
        (pl.col("timestamp") > after) & (pl.col("timestamp") <= until) & ~pl.col("is_self_transfer")
    ).select("tx_id", "timestamp", "sender_id", "receiver_id", "amount_paid_usd")
    frontier = {start}
    reached = set(frontier)
    frames = []
    for _ in range(max_hops + 1):
        step = window.filter(pl.col("sender_id").is_in(list(frontier))).collect()
        frames.append(step)
        frontier = set(step["receiver_id"].to_list()) - reached
        reached |= frontier
        if not frontier:
            break
    return pl.concat(frames).unique("tx_id").sort("timestamp", "tx_id")


class _Sweep:
    """Time-ordered allocation of tainted lots over candidate outflows."""

    def __init__(self, config: TracerConfig) -> None:
        self.config = config
        self.lots: dict[Any, deque[_Lot]] = defaultdict(deque)
        self.first_hop: dict[Any, int] = {}
        self.received: dict[Any, float] = defaultdict(float)
        self.sent: dict[Any, float] = defaultdict(float)
        self.hops: list[dict[str, Any]] = []
        self.left_trace = 0.0
        self.followed = 0

    def seed(self, account: Any, amount: float, at: datetime) -> None:  # noqa: ANN401
        self.lots[account].append(_Lot(amount, at, 0))
        self.first_hop[account] = 0
        self.received[account] += amount

    def _consume(self, account: Any, amount: float, at: datetime) -> list[_Lot]:  # noqa: ANN401
        """Take up to ``amount`` from the account's usable lots, oldest first."""
        taken: list[_Lot] = []
        remaining = amount
        for lot in self.lots[account]:
            if remaining <= _TOLERANCE:
                break
            usable = (
                lot.amount > _TOLERANCE
                and lot.arrived_at < at <= lot.arrived_at + self.config.hop_window
            )
            if usable:
                portion = min(lot.amount, remaining)
                lot.amount -= portion
                remaining -= portion
                taken.append(_Lot(portion, lot.arrived_at, lot.hop))
        return taken

    def _followable(self, amount: float, hop: int) -> bool:
        return (
            hop < self.config.max_hops
            and amount >= self.config.min_transaction_usd
            and self.followed < self.config.max_transactions
        )

    def step(self, row: dict[str, Any]) -> None:
        """Apply one candidate outflow."""
        sender, receiver = row["sender_id"], row["receiver_id"]
        taken = self._consume(sender, row["amount_paid_usd"], row["timestamp"])
        if not taken:
            return
        tainted = sum(lot.amount for lot in taken)
        hop = min(lot.hop for lot in taken)
        self.sent[sender] += tainted
        if not self._followable(row["amount_paid_usd"], hop):
            self.left_trace += tainted
            return
        self.followed += 1
        self.lots[receiver].append(_Lot(tainted, row["timestamp"], hop + 1))
        self.first_hop.setdefault(receiver, hop + 1)
        self.received[receiver] += tainted
        self.hops.append(
            {
                "hop": hop + 1,
                "tx_id": row["tx_id"],
                "timestamp": row["timestamp"],
                "sender_id": sender,
                "receiver_id": receiver,
                "amount_usd": row["amount_paid_usd"],
                "tainted_usd": tainted,
            }
        )

    def nodes(self) -> pl.DataFrame:
        rows = [
            {
                "account_id": account,
                "first_hop": hop,
                "received_tainted_usd": self.received[account],
                "sent_tainted_usd": self.sent[account],
                "recoverable_usd": sum(lot.amount for lot in self.lots[account]),
            }
            for account, hop in self.first_hop.items()
        ]
        return pl.DataFrame(rows).sort("first_hop", "account_id") if rows else pl.DataFrame()


def trace(
    transactions: pl.LazyFrame,
    disputed_tx_id: int,
    config: TracerConfig,
    analysed_at: datetime | None = None,
) -> TraceResult:
    """Trace the money of one disputed transfer.

    Args:
        transactions: the transactions table.
        disputed_tx_id: the transfer reported as fraudulent.
        config: tracing parameters.
        analysed_at: when the trace is run; only transfers up to this time exist. Defaults to
            the end of the longest possible chain of hop windows.
    """
    disputed = transactions.filter(pl.col("tx_id") == disputed_tx_id).collect()
    if disputed.height != 1:
        raise KeyError(f"transaction {disputed_tx_id} not found")
    row = disputed.row(0, named=True)
    started = row["timestamp"]
    until = analysed_at or started + config.hop_window * config.max_hops
    sweep = _Sweep(config)
    sweep.seed(row["receiver_id"], row["amount_paid_usd"], started)
    candidates = _candidate_outflows(
        transactions, row["receiver_id"], started, until, config.max_hops
    )
    # The sweep must visit outflows in time order because each one can create a lot that a
    # later outflow consumes; the candidate set is small, so a Python loop is the clear choice.
    for candidate in candidates.iter_rows(named=True):
        sweep.step(candidate)
    notes = []
    if sweep.followed >= config.max_transactions:
        notes.append("transaction cap reached; part of the flow was not followed")
    return TraceResult(
        disputed_tx_id=disputed_tx_id,
        disputed_usd=row["amount_paid_usd"],
        hops=pl.DataFrame(sweep.hops) if sweep.hops else pl.DataFrame(),
        nodes=sweep.nodes(),
        left_trace_usd=sweep.left_trace,
        followed_transactions=sweep.followed,
        notes=notes,
    )
