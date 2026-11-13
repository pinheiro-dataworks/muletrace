"""LightGBM training on point-in-time snapshots.

Training sets are large and very imbalanced (about 25 positives per 10,000 accounts). Negatives
are subsampled at a fixed rate and re-weighted by the inverse rate, which keeps the predicted
probabilities on the original scale and makes each fit several times faster. Early stopping uses
a later snapshot than any training row, and ``num_threads`` is fixed so runs are comparable.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from numpy.typing import NDArray
from pydantic import Field

from muletrace.config import StrictModel
from muletrace.models.evaluate import average_precision


class TrainingConfig(StrictModel):
    """Training parameters, read from ``configs/training.yaml``."""

    seed: int
    num_threads: int = Field(gt=0)
    negative_sample_rate: float = Field(gt=0, le=1)
    max_boost_rounds: int = Field(gt=0)
    early_stopping_rounds: int = Field(gt=0)
    base_params: dict[str, Any]
    search: dict[str, tuple[Any, ...]]
    rules_search: dict[str, tuple[float, ...]]
    backtest_test_snapshots: tuple[datetime, ...] = Field(min_length=1)

    def search_space(self) -> list[dict[str, Any]]:
        """Every combination of the search grid, in a stable order."""
        names = sorted(self.search)
        return [
            dict(zip(names, values, strict=True))
            for values in itertools.product(*(self.search[name] for name in names))
        ]


@dataclass(frozen=True)
class FittedModel:
    """A trained booster with the feature order it expects."""

    booster: lgb.Booster
    features: tuple[str, ...]
    params: dict[str, Any]

    @property
    def best_iteration(self) -> int:
        """Number of trees kept by early stopping."""
        return int(self.booster.best_iteration or self.booster.num_trees())

    def predict(self, frame: pl.DataFrame) -> NDArray[np.float64]:
        """Raw (uncalibrated) probability for every row of ``frame``."""
        matrix = frame.select(self.features).to_numpy().astype(np.float64)
        return np.asarray(self.booster.predict(matrix, num_iteration=self.best_iteration))


def subsample_negatives(
    frame: pl.DataFrame, rate: float, seed: int
) -> tuple[pl.DataFrame, NDArray[np.float64]]:
    """Keep every positive and a ``rate`` share of negatives; return rows and sample weights."""
    rng = np.random.default_rng(seed)
    labels = frame["label"].to_numpy()
    keep = labels | (rng.random(frame.height) < rate)
    weights = np.where(labels[keep], 1.0, 1.0 / rate)
    return frame.filter(pl.Series(keep)), weights


def _dataset(
    frame: pl.DataFrame, features: tuple[str, ...], weights: NDArray[np.float64] | None
) -> lgb.Dataset:
    return lgb.Dataset(
        frame.select(features).to_numpy().astype(np.float64),
        label=frame["label"].to_numpy().astype(np.float64),
        weight=weights,
        feature_name=list(features),
        categorical_feature=["entity_type"] if "entity_type" in features else "auto",
        free_raw_data=False,
    )


def fit(
    train: pl.DataFrame,
    valid: pl.DataFrame,
    features: list[str],
    params: dict[str, Any],
    config: TrainingConfig,
) -> FittedModel:
    """Fit one LightGBM model with early stopping on ``valid``."""
    ordered = tuple(features)
    sampled, weights = subsample_negatives(train, config.negative_sample_rate, config.seed)
    train_set = _dataset(sampled, ordered, weights)
    valid_set = _dataset(valid, ordered, None)
    merged = {
        **config.base_params,
        **params,
        "num_threads": config.num_threads,
        "seed": config.seed,
        "deterministic": True,
        "metric": "average_precision",
    }
    booster = lgb.train(
        merged,
        train_set,
        num_boost_round=config.max_boost_rounds,
        valid_sets=[valid_set],
        callbacks=[lgb.early_stopping(config.early_stopping_rounds, verbose=False)],
    )
    return FittedModel(booster=booster, features=ordered, params=dict(params))


def select_params(
    train: pl.DataFrame, valid: pl.DataFrame, features: list[str], config: TrainingConfig
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Try every grid point; return the best parameters and the full trial log."""
    trials = []
    for params in config.search_space():
        model = fit(train, valid, features, params, config)
        score = average_precision(valid["label"].to_numpy(), model.predict(valid))
        trials.append(
            {**params, "valid_average_precision": round(score, 5), "trees": model.best_iteration}
        )
    best = max(trials, key=lambda trial: trial["valid_average_precision"])
    return {name: best[name] for name in config.search}, trials
