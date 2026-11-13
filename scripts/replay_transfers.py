"""Replay AMLworld transfers to an SQS queue in time order.

A cheap stand-in for a live payment stream: each message is one transfer (transaction ID,
time, sender, receiver, US-dollar amount). The consumer Lambda scores the receiving account.
Credentials come from the usual AWS profile; nothing is sent without ``--queue-url``.

Usage:
    uv run python scripts/replay_transfers.py --queue-url <url>
        --start 2022-09-09T08:00 --end 2022-09-09T09:00 [--dataset HI-Small] [--limit 500]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

BATCH = 10  # SQS SendMessageBatch maximum


def messages(
    transactions: pl.LazyFrame, start: datetime, end: datetime, limit: int
) -> list[dict[str, Any]]:
    """Non-self transfers in ``[start, end)``, oldest first, as message bodies."""
    rows = (
        transactions.filter(
            (pl.col("timestamp") >= start)
            & (pl.col("timestamp") < end)
            & ~pl.col("is_self_transfer")
        )
        .sort("timestamp", "tx_id")
        .head(limit)
        .select("tx_id", "timestamp", "sender_id", "receiver_id", "amount_paid_usd")
        .collect()
    )
    return [
        {**row, "timestamp": row["timestamp"].isoformat()} for row in rows.iter_rows(named=True)
    ]


def send(client: Any, queue_url: str, bodies: list[dict[str, Any]]) -> int:  # noqa: ANN401
    """Send bodies in batches of ten; returns the number of messages accepted."""
    sent = 0
    for start in range(0, len(bodies), BATCH):
        chunk = bodies[start : start + BATCH]
        response = client.send_message_batch(
            QueueUrl=queue_url,
            Entries=[
                {"Id": str(i), "MessageBody": json.dumps(body)} for i, body in enumerate(chunk)
            ],
        )
        sent += len(response.get("Successful", []))
    return sent


def main() -> None:
    import boto3  # noqa: PLC0415 - only needed when actually sending

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--queue-url", required=True)
    parser.add_argument("--start", type=datetime.fromisoformat, required=True)
    parser.add_argument("--end", type=datetime.fromisoformat, required=True)
    parser.add_argument("--dataset", default="HI-Small")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    transactions = pl.scan_parquet(Path("data/processed") / args.dataset / "transactions.parquet")
    bodies = messages(transactions, args.start, args.end, args.limit)
    print(f"Sent {send(boto3.client('sqs'), args.queue_url, bodies)} of {len(bodies)} messages")


if __name__ == "__main__":
    main()
