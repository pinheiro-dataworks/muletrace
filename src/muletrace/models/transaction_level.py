"""External check: AMLworld's own transaction-level task.

The AMLworld paper (Altman et al., arXiv:2306.16424, Table 2) classifies *transactions* as
laundering or not, on a 60/20/20 temporal split of transaction indices ordered by time, and
reports the F1 score of the minority class. Reproducing that task with MuleTrace's tooling is a
sanity check of the data handling, not a competition: the paper's best gradient-boosting result
uses a dedicated Graph Feature Preprocessor, while the features here are simple causal window
aggregates.

Every feature of a transaction uses only transactions that happened strictly earlier (the
rolling windows are closed on the left), so the check is free of look-ahead.
"""

from __future__ import annotations

from typing import Any, Final

import lightgbm as lgb
import numpy as np
import polars as pl
from numpy.typing import NDArray

from muletrace.models.evaluate import average_precision
from muletrace.models.train import TrainingConfig, subsample_negatives

SPLIT: Final = (0.6, 0.2, 0.2)
PAPER_SOURCE: Final = "Altman et al., arXiv:2306.16424, Table 2 (minority-class F1, %)"
PAPER_TABLE_2_F1: Final[dict[str, dict[str, float]]] = {
    "HI-Small": {"GIN": 28.70, "PNA": 56.77, "GFP + LightGBM": 62.86, "GFP + XGBoost": 63.23},
    "LI-Small": {"GIN": 7.90, "PNA": 16.45, "GFP + LightGBM": 20.83, "GFP + XGBoost": 27.30},
}
_WINDOW: Final = "24h"
_PAIR_BASE: Final = 1 << 32


def _rolling(frame: pl.DataFrame, key: str, prefix: str, counterpart: str) -> pl.DataFrame:
    """Count, sum and distinct counterparts of earlier transactions of the same ``key``."""
    ordered = frame.sort(key, "timestamp", "tx_id")
    windows = ordered.rolling(
        index_column="timestamp", period=_WINDOW, closed="left", group_by=key
    ).agg(
        pl.len().alias(f"{prefix}_count_24h"),
        pl.col("amount_paid_usd").sum().alias(f"{prefix}_usd_24h"),
        pl.col(counterpart).n_unique().alias(f"{prefix}_counterparts_24h"),
    )
    aligned = windows[key].equals(ordered[key]) and windows["timestamp"].equals(
        ordered["timestamp"]
    )
    if not aligned:  # pragma: no cover - guards row alignment, which Polars does not promise
        raise RuntimeError("rolling output is not aligned with its input")
    return windows.drop(key, "timestamp").with_columns(tx_id=ordered["tx_id"])


def transaction_features(transactions: pl.DataFrame, accounts: pl.DataFrame) -> pl.DataFrame:
    """Edge attributes plus causal 24-hour aggregates of the sender, receiver and pair."""
    banks = accounts.select("account_id", "bank_id")
    edges = (
        transactions.join(
            banks.rename({"account_id": "sender_id", "bank_id": "sender_bank"}), on="sender_id"
        )
        .join(
            banks.rename({"account_id": "receiver_id", "bank_id": "receiver_bank"}),
            on="receiver_id",
        )
        # A numeric pair key: Polars returns string-keyed rolling groups in a different order
        # from the input sort, which the alignment guard in `_rolling` caught.
        .with_columns(
            pair=pl.col("sender_id").cast(pl.UInt64) * _PAIR_BASE
            + pl.col("receiver_id").cast(pl.UInt64)
        )
    )
    features = edges.select(
        "tx_id",
        "timestamp",
        "is_laundering",
        log_amount_usd=pl.col("amount_paid_usd").log1p(),
        payment_format=pl.col("payment_format").to_physical().cast(pl.Int32),
        payment_currency=pl.col("payment_currency").to_physical().cast(pl.Int32),
        cross_currency=pl.col("payment_currency") != pl.col("receiving_currency"),
        same_bank=pl.col("sender_bank") == pl.col("receiver_bank"),
        is_self_transfer="is_self_transfer",
        hour=pl.col("timestamp").dt.hour(),
        weekday=pl.col("timestamp").dt.weekday(),
    )
    for key, prefix, counterpart in (
        ("sender_id", "sender_out", "receiver_id"),
        ("receiver_id", "receiver_in", "sender_id"),
        ("pair", "pair", "tx_id"),
    ):
        features = features.join(_rolling(edges, key, prefix, counterpart), on="tx_id")
    return features.drop("pair_counterparts_24h").sort("timestamp", "tx_id")


def temporal_split(frame: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """60/20/20 split of the rows ordered by ``(timestamp, tx_id)``, as in the paper."""
    n = frame.height
    first, second = int(n * SPLIT[0]), int(n * (SPLIT[0] + SPLIT[1]))
    return frame[:first], frame[first:second], frame[second:]


def best_f1_threshold(
    labels: NDArray[np.bool_], scores: NDArray[np.float64]
) -> tuple[float, float]:
    """Threshold that maximises F1 on ``labels``; returns ``(threshold, f1)``."""
    order = np.argsort(-scores, kind="stable")
    hits = np.cumsum(labels[order])
    alerted = np.arange(1, labels.size + 1)
    f1 = 2 * hits / (alerted + labels.sum())
    best = int(np.argmax(f1))
    return float(scores[order][best]), float(f1[best])


def _f1_at(
    labels: NDArray[np.bool_], scores: NDArray[np.float64], threshold: float
) -> dict[str, float]:
    predicted = scores >= threshold
    hits = float(np.sum(predicted & labels))
    precision = hits / predicted.sum() if predicted.sum() else 0.0
    recall = hits / labels.sum() if labels.sum() else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "f1_percent": round(100 * f1, 2),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
    }


def run_transaction_check(
    transactions: pl.DataFrame, accounts: pl.DataFrame, config: TrainingConfig, dataset: str
) -> dict[str, Any]:
    """Train on the first 60%, pick the F1 threshold on the next 20%, report on the last 20%."""
    frame = transaction_features(transactions, accounts).rename({"is_laundering": "label"})
    names = [c for c in frame.columns if c not in ("tx_id", "timestamp", "label")]
    train, valid, test = temporal_split(frame)
    sampled, weights = subsample_negatives(train, config.negative_sample_rate, config.seed)

    def matrix(part: pl.DataFrame) -> NDArray[np.float64]:
        return part.select(names).to_numpy().astype(np.float64)

    params = {
        **config.base_params,
        "num_leaves": 63,
        "num_threads": config.num_threads,
        "seed": config.seed,
        "deterministic": True,
        "metric": "average_precision",
    }
    booster = lgb.train(
        params,
        lgb.Dataset(
            matrix(sampled), label=sampled["label"].to_numpy(), weight=weights, feature_name=names
        ),
        num_boost_round=config.max_boost_rounds,
        valid_sets=[
            lgb.Dataset(matrix(valid), label=valid["label"].to_numpy(), feature_name=names)
        ],
        callbacks=[lgb.early_stopping(config.early_stopping_rounds, verbose=False)],
    )
    valid_scores = np.asarray(booster.predict(matrix(valid), num_iteration=booster.best_iteration))
    test_scores = np.asarray(booster.predict(matrix(test), num_iteration=booster.best_iteration))
    threshold, valid_f1 = best_f1_threshold(valid["label"].to_numpy(), valid_scores)
    test_labels = test["label"].to_numpy()
    return {
        "dataset": dataset,
        "rows": {"train": train.height, "valid": valid.height, "test": test.height},
        "laundering": {
            "train": int(train["label"].sum()),
            "valid": int(valid["label"].sum()),
            "test": int(test["label"].sum()),
        },
        "features": names,
        "trees": int(booster.best_iteration),
        "threshold": threshold,
        "valid_f1_percent": round(100 * valid_f1, 2),
        "test": {
            **_f1_at(test_labels, test_scores, threshold),
            "average_precision": round(average_precision(test_labels, test_scores), 4),
        },
        "paper_reference": {"source": PAPER_SOURCE, **PAPER_TABLE_2_F1.get(dataset, {})},
    }
