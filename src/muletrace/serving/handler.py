"""Scoring Lambda behind an HTTP API: ``GET /score/{account_id}?as_of=YYYY-MM-DD``.

The model artefact is loaded once per container, at the first request (from S3 when
``MODEL_URI`` is set, see :mod:`muletrace.serving.model_source`), and kept for the life of the
container; the feature vector is read from the online store that the daily batch job wrote.
The response carries the calibrated probability, capped for display (isotonic calibration
saturates at 1.0 for the highest scores, which over-states certainty), and the top reason
codes. Each scored request is also logged as one JSON line, the inference capture that the
drift job reads.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from functools import cache
from typing import Any, Final

import numpy as np

from muletrace.models.artifact import ModelArtifact, load_artifact
from muletrace.serving.feature_client import (
    DynamoDBFeatureStore,
    FeatureStore,
    decode_features,
)
from muletrace.serving.model_source import resolve_model_dir

logger = logging.getLogger("muletrace.serving")
logger.setLevel(logging.INFO)

_DATE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_PROBABILITY_CAP: Final = 0.99
REASON_CODES: Final = 3


@dataclass(frozen=True)
class ScoringService:
    """Everything a request needs, built once per container."""

    artifact: ModelArtifact
    store: FeatureStore
    dataset: str
    probability_cap: float

    def score(self, account_id: int, as_of: str) -> dict[str, Any] | None:
        """Score one account at one as-of date, or ``None`` if it has no features."""
        encoded = self.store.get(self.dataset, account_id, as_of)
        if encoded is None:
            return None
        vector = decode_features(encoded, self.artifact.features)[np.newaxis, :]
        raw, probability = self.artifact.score_matrix(vector)
        contributions = self.artifact.contributions_matrix(vector)[0]
        top = np.argsort(-contributions, kind="stable")[:REASON_CODES]
        return {
            "account_id": account_id,
            "as_of": as_of,
            "dataset": self.dataset,
            "probability": round(min(float(probability[0]), self.probability_cap), 6),
            "probability_capped": bool(probability[0] > self.probability_cap),
            "raw_score": round(float(raw[0]), 6),
            "reasons": [
                {
                    "feature": self.artifact.features[i],
                    "value": None if np.isnan(vector[0, i]) else float(vector[0, i]),
                    "contribution": round(float(contributions[i]), 4),
                }
                for i in top
                if contributions[i] > 0
            ],
            "model": self.artifact.metadata.get("model"),
            "model_trained_on": self.artifact.metadata.get("trained_on_snapshots", [])[-1:],
        }


@cache
def service() -> ScoringService:
    """Build the service from environment variables on the first request of a container."""
    return ScoringService(
        artifact=load_artifact(resolve_model_dir()),
        store=DynamoDBFeatureStore(os.environ["FEATURE_TABLE"]),
        dataset=os.environ.get("DATASET", "HI-Small"),
        probability_cap=float(os.environ.get("PROBABILITY_CAP", DEFAULT_PROBABILITY_CAP)),
    )


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _parse(event: dict[str, Any]) -> tuple[int, str] | str:
    """Account and as-of date from an HTTP API event, or an error message."""
    raw_account = (event.get("pathParameters") or {}).get("account_id", "")
    as_of = (event.get("queryStringParameters") or {}).get("as_of", "")
    if not str(raw_account).isdigit():
        return "account_id must be a non-negative integer"
    if not _DATE.match(as_of):
        return "as_of must be a date in YYYY-MM-DD format"
    return int(raw_account), as_of


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    """AWS Lambda entry point for API Gateway HTTP API (payload format 2.0)."""
    parsed = _parse(event)
    if isinstance(parsed, str):
        return _response(400, {"error": parsed})
    account_id, as_of = parsed
    result = service().score(account_id, as_of)
    if result is None:
        return _response(404, {"error": "no features for this account and date"})
    logger.info(
        json.dumps(
            {
                "event": "inference",
                "account_id": account_id,
                "as_of": as_of,
                "probability": result["probability"],
                "raw_score": result["raw_score"],
            }
        )
    )
    return _response(200, result)
