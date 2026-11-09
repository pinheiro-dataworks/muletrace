"""Graph features on the past-to-future transfer graph.

At as-of time *t* the graph has one directed edge ``sender → receiver`` for every distinct pair
that transacted strictly before *t* (self-transfers excluded). Everything is computed with sparse
matrices, once per snapshot, and returned for the scored population only:

* in- and out-degree (distinct counterparties over the whole history);
* PageRank;
* one-hop aggregates of the senders (their mean out-degree and mean PageRank);
* **neighbour labels**: senders and receivers already *confirmed* as mules at *t*, and senders
  whose own senders are confirmed (two hops upstream). A confirmation after *t* is invisible.

Connected components were tried and dropped: on the trailing week of HI-Small one weakly
connected component holds almost every account, so its size carries no information (ADR-007).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import polars as pl
from numpy.typing import NDArray
from scipy import sparse

from muletrace.features.asof import history_before
from muletrace.features.config import GraphConfig

FloatArray = NDArray[np.float64]


def _adjacency(edges: pl.DataFrame, n_nodes: int) -> sparse.csr_matrix:
    """Binary adjacency matrix ``A[i, j] = 1`` when ``i`` sent money to ``j``."""
    rows = edges["sender_id"].to_numpy().astype(np.int64)
    cols = edges["receiver_id"].to_numpy().astype(np.int64)
    data = np.ones(rows.size, dtype=np.float64)
    return sparse.csr_matrix((data, (rows, cols)), shape=(n_nodes, n_nodes))


def pagerank(adjacency: sparse.csr_matrix, config: GraphConfig) -> FloatArray:
    """PageRank by power iteration; dangling nodes spread their mass uniformly."""
    n_nodes = adjacency.shape[0]
    out_degree = np.asarray(adjacency.sum(axis=1)).ravel()
    inverse = np.divide(1.0, out_degree, out=np.zeros(n_nodes), where=out_degree > 0)
    transition = sparse.diags(inverse) @ adjacency
    rank = np.full(n_nodes, 1.0 / n_nodes)
    damping = config.pagerank_damping
    for _ in range(config.pagerank_max_iterations):
        dangling = rank[out_degree == 0].sum()
        updated = damping * (transition.T @ rank + dangling / n_nodes) + (1 - damping) / n_nodes
        converged = np.abs(updated - rank).sum() < config.pagerank_tolerance
        rank = updated
        if converged:
            break
    return np.asarray(rank, dtype=np.float64)


def _confirmed_mask(confirmed: pl.DataFrame, as_of: datetime, n_nodes: int) -> FloatArray:
    known = confirmed.filter(pl.col("confirmed_at") <= as_of)["account_id"].to_numpy()
    mask = np.zeros(n_nodes, dtype=np.float64)
    mask[known.astype(np.int64)] = 1.0
    return mask


def graph_features(
    *,
    transactions: pl.LazyFrame,
    confirmed: pl.DataFrame,
    population: pl.DataFrame,
    as_of: datetime,
    n_nodes: int,
    config: GraphConfig,
) -> pl.DataFrame:
    """Graph features at ``as_of`` for every account in ``population``."""
    edges = (
        history_before(transactions, as_of)
        .filter(~pl.col("is_self_transfer"))
        .select("sender_id", "receiver_id")
        .unique()
        .collect()
    )
    adjacency = _adjacency(edges, n_nodes)
    incoming = adjacency.T.tocsr()
    in_degree = np.asarray(adjacency.sum(axis=0)).ravel()
    out_degree = np.asarray(adjacency.sum(axis=1)).ravel()
    rank = pagerank(adjacency, config)
    mules = _confirmed_mask(confirmed, as_of, n_nodes)
    confirmed_senders = incoming @ mules
    upstream = incoming @ (confirmed_senders > 0).astype(np.float64)
    safe_in = np.where(in_degree > 0, in_degree, 1.0)

    ids = population["account_id"].to_numpy().astype(np.int64)
    columns: dict[str, FloatArray] = {
        "in_degree": in_degree,
        "out_degree": out_degree,
        "pagerank": rank * n_nodes,  # scaled so that the average account has rank 1
        "sender_mean_out_degree": (incoming @ out_degree) / safe_in,
        "sender_mean_pagerank": (incoming @ (rank * n_nodes)) / safe_in,
        "confirmed_mule_senders": confirmed_senders,
        "confirmed_mule_receivers": adjacency @ mules,
        "senders_with_confirmed_senders": upstream,
    }
    return pl.DataFrame(
        {"account_id": population["account_id"], **{k: v[ids] for k, v in columns.items()}}
    )
