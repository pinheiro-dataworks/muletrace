"""Online feature store: the batch job writes feature vectors, the scoring Lambda reads them.

DynamoDB stores numbers as decimals and has no NaN, which is where batch/online skew usually
creeps in. Encoding is therefore explicit and lossless:

* a float is written as ``Decimal(repr(value))``; ``repr`` gives the shortest string that
  round-trips, so the float read back is bit-for-bit the one written;
* a missing value (``None`` or NaN) is simply not written, and is read back as NaN, which is
  how LightGBM treats missing values in the batch path too.

Items are keyed by ``pk = "<dataset>#<account_id>"`` and ``sk = <as-of date, ISO>``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

FEATURES_ATTRIBUTE = "features"


def item_key(dataset: str, account_id: int, as_of: str) -> dict[str, str]:
    """Primary key of one feature vector."""
    return {"pk": f"{dataset}#{account_id}", "sk": as_of}


def encode_features(values: Mapping[str, float | None]) -> dict[str, Decimal]:
    """Lossless DynamoDB encoding; missing values are dropped."""
    return {
        name: Decimal(repr(float(value)))
        for name, value in values.items()
        if value is not None and not math.isnan(float(value))
    }


def decode_features(encoded: Mapping[str, Any], order: tuple[str, ...]) -> NDArray[np.float64]:
    """Feature vector in ``order``; absent features become NaN."""
    return np.array(
        [float(encoded[name]) if name in encoded else math.nan for name in order], dtype=np.float64
    )


class FeatureStore(Protocol):
    """Where the scoring Lambda reads feature vectors from."""

    def get(self, dataset: str, account_id: int, as_of: str) -> dict[str, Any] | None:
        """Encoded features of one account at one as-of date, or ``None``."""

    def put_many(self, items: Iterable[dict[str, Any]]) -> int:
        """Write full items (key plus features); returns how many were written."""


@dataclass
class InMemoryFeatureStore:
    """Dictionary-backed store for tests and local runs."""

    items: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def get(self, dataset: str, account_id: int, as_of: str) -> dict[str, Any] | None:
        """Encoded features of one account at one as-of date, or ``None``."""
        key = item_key(dataset, account_id, as_of)
        item = self.items.get((key["pk"], key["sk"]))
        return None if item is None else dict(item[FEATURES_ATTRIBUTE])

    def put_many(self, items: Iterable[dict[str, Any]]) -> int:
        """Write full items; returns how many were written."""
        count = 0
        for item in items:
            self.items[(item["pk"], item["sk"])] = item
            count += 1
        return count


class DynamoDBFeatureStore:
    """Feature store on a DynamoDB table with on-demand capacity."""

    def __init__(self, table_name: str, table: Any | None = None) -> None:  # noqa: ANN401
        if table is None:
            import boto3  # noqa: PLC0415 - only the AWS path needs it

            table = boto3.resource("dynamodb").Table(table_name)
        self.table = table

    def get(self, dataset: str, account_id: int, as_of: str) -> dict[str, Any] | None:
        """Encoded features of one account at one as-of date, or ``None``."""
        response = self.table.get_item(Key=item_key(dataset, account_id, as_of))
        item = response.get("Item")
        return None if item is None else dict(item[FEATURES_ATTRIBUTE])

    def put_many(self, items: Iterable[dict[str, Any]]) -> int:
        """Write items with the batch writer (25 per request, retried by boto3)."""
        count = 0
        with self.table.batch_writer(overwrite_by_pkeys=["pk", "sk"]) as writer:
            for item in items:
                writer.put_item(Item=item)
                count += 1
        return count
