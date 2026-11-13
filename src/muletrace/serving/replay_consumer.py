"""SQS consumer for replayed transfers: check every incoming transfer's receiving account.

``scripts/replay_transfers.py`` sends AMLworld transfers to an SQS queue in time order, which is
a cheap stand-in for a live payment stream (no Kinesis shards to pay for). For each transfer the
consumer scores the receiving account with that day's features and logs an alert when the
calibrated probability reaches the threshold. Failed messages are reported individually
(partial batch response), so one bad record does not re-deliver the whole batch.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from muletrace.serving.handler import ScoringService, service

logger = logging.getLogger("muletrace.replay")
logger.setLevel(logging.INFO)

DEFAULT_ALERT_THRESHOLD = 0.5


def check_transfer(
    record: dict[str, Any], scorer: ScoringService, threshold: float
) -> dict[str, Any] | None:
    """Score the receiver of one replayed transfer; return an alert or ``None``."""
    transfer = json.loads(record["body"])
    as_of = str(transfer["timestamp"])[:10]
    result = scorer.score(int(transfer["receiver_id"]), as_of)
    if result is None or result["probability"] < threshold:
        return None
    return {
        "event": "receiver_alert",
        "tx_id": transfer["tx_id"],
        "receiver_id": transfer["receiver_id"],
        "as_of": as_of,
        "probability": result["probability"],
        "reasons": [reason["feature"] for reason in result["reasons"]],
    }


def process_batch(
    event: dict[str, Any], scorer: ScoringService, threshold: float
) -> dict[str, Any]:
    """Process an SQS batch; returns the partial-batch failure report and the alerts."""
    failures, alerts = [], []
    for record in event.get("Records", []):
        try:
            alert = check_transfer(record, scorer, threshold)
        except (KeyError, ValueError, TypeError):
            logger.exception("Could not process message %s", record.get("messageId"))
            failures.append({"itemIdentifier": record.get("messageId")})
            continue
        if alert is not None:
            logger.info(json.dumps(alert))
            alerts.append(alert)
    return {"batchItemFailures": failures, "alerts": len(alerts)}


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:  # pragma: no cover
    """Lambda entry point for the SQS event source."""
    threshold = float(os.environ.get("ALERT_THRESHOLD", DEFAULT_ALERT_THRESHOLD))
    return process_batch(event, service(), threshold)
