"""Evaluate the tracer against AMLworld's own labels.

AMLworld propagates the laundering tag through later transfers of laundered money (paper,
Section 3.4), so the labels give a ground truth for where the money went. For every accepted
MED-style dispute in the Pix layer (a transfer that brings laundered money into a mule account),
the tracer runs and is scored on:

* **precision** — the share of the tainted amount it followed that moved through transfers
  labelled as laundering;
* **coverage** — the share of laundering transfers sent by the accounts the trace reached, after
  the dispute and inside the trace's time range, that the trace followed;
* where the money is at the end of the trace window, as shares of the disputed amount: still in
  a traced account (the recoverable estimate), in a traced account beyond the first receiving
  account, or gone from the trace (hop limit, minimum amount or transaction cap).

Without balances, money that no followed transfer moved stays "located" by construction, so the
recoverable share is an upper bound on what a return could reach, not a recovery rate.

These are measurements of the tracer's allocation rule on synthetic data, not of MED 2.0.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import polars as pl

from muletrace.tracing.med_tracer import TracerConfig, TraceResult, trace


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _followed(result: TraceResult, transactions: pl.LazyFrame) -> pl.DataFrame:
    """Followed hops with their laundering label (empty frame when nothing was followed)."""
    if not result.hops.height:
        return pl.DataFrame(
            schema={"tx_id": pl.UInt32, "tainted_usd": pl.Float64, "is_laundering": pl.Boolean}
        )
    labels = (
        transactions.filter(pl.col("tx_id").is_in(result.hops["tx_id"].to_list()))
        .select("tx_id", "is_laundering")
        .collect()
    )
    return result.hops.join(labels, on="tx_id", how="left").select(
        "tx_id", "tainted_usd", "is_laundering"
    )


def _laundering_sent(result: TraceResult, transactions: pl.LazyFrame, until: datetime) -> set[int]:
    """Laundering transfers sent by reached accounts after the dispute, up to ``until``."""
    disputed_at = (
        transactions.filter(pl.col("tx_id") == result.disputed_tx_id).collect()["timestamp"].item()
    )
    truth = transactions.filter(
        pl.col("sender_id").is_in(result.nodes["account_id"].to_list())
        & pl.col("is_laundering")
        & ~pl.col("is_self_transfer")
        & (pl.col("timestamp") > disputed_at)
        & (pl.col("timestamp") <= until)
    )
    return set(truth.select("tx_id").collect()["tx_id"].to_list())


def _score(result: TraceResult, transactions: pl.LazyFrame, until: datetime) -> dict[str, Any]:
    followed = _followed(result, transactions)
    truth = _laundering_sent(result, transactions, until)
    laundering_usd = float(followed.filter(pl.col("is_laundering"))["tainted_usd"].sum())
    return {
        **result.summary(),
        "precision_usd": _ratio(laundering_usd, float(followed["tainted_usd"].sum())),
        "coverage": _ratio(len(truth & set(followed["tx_id"].to_list())), len(truth)),
        "recoverable_share": _ratio(result.recoverable_usd, result.disputed_usd),
        "beyond_first_account_share": _ratio(
            float(result.nodes.filter(pl.col("first_hop") > 0)["recoverable_usd"].sum()),
            result.disputed_usd,
        ),
        "left_trace_share": _ratio(result.left_trace_usd, result.disputed_usd),
    }


def _median(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(median(present), 4) if present else None


def evaluate_tracer(dataset_dir: Path, config: TracerConfig) -> dict[str, Any]:
    """Trace every accepted dispute of a dataset and summarise the scores."""
    transactions = pl.scan_parquet(dataset_dir / "transactions.parquet")
    disputes = pl.read_parquet(dataset_dir / "pix_layer" / "pix_disputes.parquet").filter(
        pl.col("outcome") == "accepted"
    )
    rows = []
    for tx_id in disputes["tx_id"].to_list():
        result = trace(transactions, tx_id, config)
        started = transactions.filter(pl.col("tx_id") == tx_id).collect()["timestamp"].item()
        rows.append(_score(result, transactions, started + config.hop_window * config.max_hops))
    keys = (
        "precision_usd",
        "coverage",
        "recoverable_share",
        "beyond_first_account_share",
        "left_trace_share",
    )
    return {
        "dataset": dataset_dir.name,
        "config": config.model_dump(),
        "disputes_traced": len(rows),
        "disputes_with_onward_hops": sum(1 for row in rows if row["hops_followed"] > 0),
        "median": {key: _median([row[key] for row in rows]) for key in keys},
        "median_with_onward_hops": {
            key: _median([row[key] for row in rows if row["hops_followed"] > 0]) for key in keys
        },
        "median_accounts_reached": _median([float(row["accounts_reached"]) for row in rows]),
        "max_hop_reached": max((row["max_hop_reached"] for row in rows), default=0),
        "per_dispute": rows,
    }
