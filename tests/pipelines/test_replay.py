from datetime import datetime
from pathlib import Path

import polars as pl
from scripts.replay_transfers import messages, send


def test_replay_messages_and_batches(world: Path) -> None:
    transactions = pl.scan_parquet(
        world / "bucket" / "data" / "processed" / "HI-Small" / "transactions.parquet"
    )
    bodies = messages(transactions, datetime(2022, 9, 2), datetime(2022, 9, 3), limit=25)
    assert len(bodies) == 25
    assert [b["timestamp"] for b in bodies] == sorted(b["timestamp"] for b in bodies)

    class Queue:
        def __init__(self) -> None:
            self.batches: list[int] = []

        def send_message_batch(self, QueueUrl: str, Entries: list[dict]) -> dict:  # noqa: N803
            assert QueueUrl == "https://queue"
            self.batches.append(len(Entries))
            return {"Successful": Entries}

    queue = Queue()
    assert send(queue, "https://queue", bodies) == 25
    assert queue.batches == [10, 10, 5]
