"""Daily batch scoring: write feature vectors to the online store and score every account.

This is the batch side of the batch/online parity contract: the vectors it writes are the ones
the scoring Lambda reads, through the same lossless encoding.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import polars as pl

from muletrace.models.artifact import ModelArtifact
from muletrace.serving.feature_client import FEATURES_ATTRIBUTE, encode_features, item_key


def feature_items(
    snapshot: pl.DataFrame, features: tuple[str, ...], dataset: str
) -> Iterator[dict[str, Any]]:
    """One store item per account of a snapshot."""
    for row in snapshot.select("account_id", "as_of", *features).iter_rows(named=True):
        key = item_key(dataset, int(row["account_id"]), row["as_of"].date().isoformat())
        yield {**key, FEATURES_ATTRIBUTE: encode_features({name: row[name] for name in features})}


def score_snapshot(snapshot: pl.DataFrame, artifact: ModelArtifact) -> pl.DataFrame:
    """Raw score and calibrated probability for every account of a snapshot."""
    raw, probability = artifact.score_frame(snapshot)
    return snapshot.select("account_id", "as_of").with_columns(
        raw_score=pl.Series(raw), probability=pl.Series(probability)
    )
