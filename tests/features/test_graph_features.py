from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from polars.testing import assert_frame_equal

from muletrace.config import CONFIG_DIR, load_config
from muletrace.data.labels import confirmations, mule_events
from muletrace.features.config import FeatureConfig, GraphConfig
from muletrace.features.graph_features import _adjacency, graph_features, pagerank
from tests.fixtures.frames import T0, rows_strategy, transactions_frame

GRAPH = load_config(FeatureConfig, CONFIG_DIR / "features.yaml").graph
AS_OF = T0 + timedelta(days=2)
N_NODES = 7


def _features(frame: pl.DataFrame, confirmed: pl.DataFrame, as_of: datetime) -> pl.DataFrame:
    population = pl.DataFrame(
        {"account_id": list(range(N_NODES))}, schema={"account_id": pl.UInt32}
    )
    return graph_features(
        transactions=frame.lazy(),
        confirmed=confirmed,
        population=population,
        as_of=as_of,
        n_nodes=N_NODES,
        config=GRAPH,
    )


def test_pagerank_of_a_cycle_is_uniform_and_sums_to_one() -> None:
    edges = pl.DataFrame({"sender_id": [0, 1, 2], "receiver_id": [1, 2, 0]})
    rank = pagerank(_adjacency(edges, 3), GRAPH)
    assert rank == pytest.approx(np.full(3, 1 / 3))


def test_pagerank_handles_dangling_nodes() -> None:
    edges = pl.DataFrame({"sender_id": [0, 1], "receiver_id": [2, 2]})
    rank = pagerank(_adjacency(edges, 3), GRAPH)
    assert rank.sum() == pytest.approx(1.0)
    assert rank[2] > rank[0] == pytest.approx(rank[1])


def test_pagerank_stops_at_the_iteration_cap() -> None:
    capped = GraphConfig(pagerank_damping=0.85, pagerank_max_iterations=1, pagerank_tolerance=1e-30)
    edges = pl.DataFrame({"sender_id": [0, 1], "receiver_id": [2, 2]})
    assert pagerank(_adjacency(edges, 3), capped).sum() == pytest.approx(1.0)


def test_degrees_and_neighbour_labels() -> None:
    rows = [
        (0, 1, 3, 10.0, True),  # 1 -> 3 laundering: account 3 becomes a mule at T0
        (10, 2, 3, 10.0, False),
        (20, 3, 4, 10.0, False),
        (30, 5, 1, 10.0, False),
        (40, 4, 4, 10.0, False),  # self-transfer, ignored
    ]
    frame = transactions_frame(rows)
    confirmed = confirmations(mule_events(frame.lazy()), timedelta(hours=1))
    features = _features(frame, confirmed, AS_OF).sort("account_id")
    row = {r["account_id"]: r for r in features.iter_rows(named=True)}
    assert (row[3]["in_degree"], row[3]["out_degree"]) == (2, 1)
    assert row[4]["confirmed_mule_senders"] == 1  # account 3 is confirmed by AS_OF
    assert row[1]["confirmed_mule_receivers"] == 1
    assert row[3]["sender_mean_out_degree"] == 1.0
    # Account 4's sender (3) has a confirmed sender? No: 3's senders are 1 and 2, not mules.
    assert row[4]["senders_with_confirmed_senders"] == 0
    assert row[6]["in_degree"] == 0
    assert row[6]["sender_mean_out_degree"] == 0.0


def test_a_confirmation_after_as_of_is_invisible() -> None:
    rows = [(0, 1, 3, 10.0, True), (20, 3, 4, 10.0, False)]
    frame = transactions_frame(rows)
    late = confirmations(mule_events(frame.lazy()), timedelta(days=5))
    features = _features(frame, late, AS_OF)
    assert features["confirmed_mule_senders"].sum() == 0
    assert features["confirmed_mule_receivers"].sum() == 0


@settings(max_examples=40, deadline=None)
@given(past=rows_strategy, future=rows_strategy, delay=st.integers(min_value=0, max_value=96))
def test_graph_features_ignore_the_future(past, future, delay) -> None:
    offset = int((AS_OF - T0).total_seconds() // 60)
    shifted = [(offset + minute, *rest) for minute, *rest in future]
    before = transactions_frame(past)
    after = transactions_frame(past + shifted)
    # Confirmations come from the full history (future mules included) but only those
    # confirmed by AS_OF may influence the features.
    confirmed = confirmations(mule_events(after.lazy()), timedelta(hours=delay))
    assert_frame_equal(_features(before, confirmed, AS_OF), _features(after, confirmed, AS_OF))
