"""Batch/online parity: the Lambda reads exactly the vector the batch job wrote."""

import numpy as np
import polars as pl

from muletrace.serving.batch import score_snapshot
from muletrace.serving.feature_client import decode_features
from muletrace.serving.handler import ScoringService


def test_batch_and_online_produce_the_same_vector_and_score(
    service: ScoringService, snapshot: pl.DataFrame
) -> None:
    batch = score_snapshot(snapshot, service.artifact)
    batch_matrix = snapshot.select(service.artifact.features).to_numpy().astype(np.float64)
    for row, account_id in enumerate(snapshot["account_id"].to_list()):
        encoded = service.store.get("HI-Small", account_id, "2022-09-09")
        assert encoded is not None
        online = decode_features(encoded, service.artifact.features)
        np.testing.assert_array_equal(online, batch_matrix[row])
        result = service.score(account_id, "2022-09-09")
        assert result is not None
        expected = min(float(batch["probability"][row]), 0.99)
        assert result["probability"] == round(expected, 6)
        assert result["raw_score"] == round(float(batch["raw_score"][row]), 6)
