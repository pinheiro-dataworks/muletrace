from pathlib import Path

import polars as pl
import pytest

from muletrace.tracing.evaluate import evaluate_tracer
from muletrace.tracing.med_tracer import TracerConfig
from tests.fixtures.frames import transactions_frame

CONFIG = TracerConfig(max_hops=3, hop_window_hours=72, min_transaction_usd=10, max_transactions=50)


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    rows = [
        (0, 0, 1, 100.0, True),  # tx 0: disputed, enters mule 1
        (10, 1, 2, 60.0, True),  # laundering hop, followed
        (20, 1, 3, 30.0, False),  # ordinary hop, followed (precision drops)
        (30, 2, 4, 15.0, True),  # laundering hop, followed
        (40, 5, 6, 10.0, False),  # unrelated
        (50, 0, 7, 20.0, True),  # tx 5: second dispute with no onward movement
    ]
    transactions_frame(rows).write_parquet(tmp_path / "transactions.parquet")
    (tmp_path / "pix_layer").mkdir()
    pl.DataFrame(
        {"tx_id": [0, 5, 4], "outcome": ["accepted", "accepted", "rejected"]}
    ).write_parquet(tmp_path / "pix_layer" / "pix_disputes.parquet")
    return tmp_path


def test_scores_against_laundering_labels(dataset: Path) -> None:
    report = evaluate_tracer(dataset, CONFIG)
    assert report["disputes_traced"] == 2
    first, second = report["per_dispute"]
    assert first["precision_usd"] == pytest.approx(75 / 105, abs=1e-4)
    assert first["coverage"] == 1.0
    assert first["recoverable_share"] + first["left_trace_share"] == pytest.approx(1.0)
    # Accounts 2, 3 and 4 hold 45 + 30 + 15 of the 100 disputed.
    assert first["beyond_first_account_share"] == pytest.approx(0.9)
    assert report["disputes_with_onward_hops"] == 1
    assert report["median_with_onward_hops"]["beyond_first_account_share"] == pytest.approx(0.9)
    assert second["precision_usd"] is None  # nothing was followed
    assert second["coverage"] is None  # no laundering left the reached accounts
    assert report["median"]["recoverable_share"] is not None
    assert report["max_hop_reached"] == 2
