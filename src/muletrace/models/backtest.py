"""Rolling-origin temporal backtest of the model ladder.

For every test snapshot *t* the fold validates on the snapshot one horizon earlier (whose labels
are fully known by *t*) and trains on every snapshot before that. Training and validation labels
are recomputed with ``known_by = t``, so no confirmation after *t* is ever used. The ladder:

1. ``rules_hand_set`` — the rules with the thresholds in ``configs/rules.yaml``;
2. ``rules_tuned`` — the same rules with thresholds chosen on the fold's training and validation
   snapshots (the honest version of the baseline);
3. ``lgbm_tabular`` — LightGBM on account behaviour features;
4. ``lgbm_tabular_graph`` — LightGBM on behaviour plus graph features.

LightGBM hyper-parameters are chosen on the first fold's validation snapshot and then frozen.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import numpy as np
import polars as pl

from muletrace.features.build import model_features
from muletrace.features.config import FeatureConfig
from muletrace.models.calibration import IsotonicCalibrator
from muletrace.models.evaluate import alert_count, top_k_mask
from muletrace.models.explain import contributions, global_importance
from muletrace.models.rules_baseline import RulesConfig, score_rules
from muletrace.models.train import FittedModel, TrainingConfig, fit, select_params
from muletrace.tracking import RunLogger

logger = logging.getLogger(__name__)

RULE_MODELS: Final = ("rules_hand_set", "rules_tuned")
LGBM_MODELS: Final = {"lgbm_tabular": False, "lgbm_tabular_graph": True}
LADDER: Final = (*RULE_MODELS, *LGBM_MODELS)
_SECONDS_PER_DAY: Final = 86_400


@dataclass(frozen=True)
class Fold:
    """One step of the rolling origin."""

    test_at: datetime
    valid_at: datetime
    train_at: tuple[datetime, ...]


def make_folds(
    snapshot_times: list[datetime], test_times: tuple[datetime, ...], horizon: timedelta
) -> list[Fold]:
    """Folds whose validation labels are complete at test time and whose training is earlier."""
    folds = []
    for test_at in test_times:
        valid_at = test_at - horizon
        train_at = tuple(s for s in snapshot_times if s < valid_at)
        if valid_at not in snapshot_times or not train_at:
            raise ValueError(f"not enough history before {test_at:%Y-%m-%d} for a fold")
        folds.append(Fold(test_at, valid_at, train_at))
    return folds


def with_known_labels(frame: pl.DataFrame, known_by: datetime) -> pl.DataFrame:
    """Relabel so that only confirmations at or before ``known_by`` count as positives."""
    return frame.with_columns(
        label=pl.col("label") & (pl.col("label_confirmed_at") <= known_by).fill_null(value=False)
    )


def add_key_age(snapshots: pl.DataFrame, keys: pl.DataFrame) -> pl.DataFrame:
    """Join the Pix key age at each snapshot (used by the rules only, never by models)."""
    return (
        snapshots.join(keys.select("account_id", "registered_at"), on="account_id", how="left")
        .with_columns(
            key_age_days=(pl.col("as_of") - pl.col("registered_at")).dt.total_seconds()
            / _SECONDS_PER_DAY
        )
        .drop("registered_at")
    )


def pooled_recall(
    frame: pl.DataFrame, score: str, tie_breaker: str, alerts_per_10k: float
) -> float:
    """Recall at the budget, pooled over the snapshots in ``frame``."""
    hits = positives = 0
    for _, snapshot in frame.group_by("as_of"):
        labels = snapshot["label"].to_numpy()
        k = alert_count(snapshot.height, alerts_per_10k)
        mask = top_k_mask(
            snapshot[score].cast(pl.Float64).to_numpy(),
            k,
            snapshot[tie_breaker].fill_null(0).cast(pl.Float64).to_numpy(),
        )
        hits += int(np.sum(labels & mask))
        positives += int(labels.sum())
    return hits / positives if positives else 0.0


def tune_rules(
    frame: pl.DataFrame,
    rules: RulesConfig,
    search: dict[str, tuple[float, ...]],
    alerts_per_10k: float,
) -> tuple[RulesConfig, float]:
    """Choose rule thresholds that maximise pooled recall on ``frame``; ties keep the first."""
    names = sorted(search)
    best: tuple[RulesConfig, float] | None = None
    for values in itertools.product(*(search[name] for name in names)):
        thresholds = dict(zip(names, values, strict=True))
        candidate = rules.model_copy(
            update={
                "rules": tuple(
                    rule.model_copy(update={"threshold": thresholds.get(rule.name, rule.threshold)})
                    for rule in rules.rules
                )
            }
        )
        recall = pooled_recall(
            score_rules(frame, candidate), "rules_score", rules.tie_breaker, alerts_per_10k
        )
        if best is None or recall > best[1]:
            best = (candidate, recall)
    if best is None:
        raise ValueError("the rules search grid is empty")
    return best


@dataclass
class BacktestResult:
    """Everything the report needs."""

    predictions: pl.DataFrame
    chosen_params: dict[str, dict[str, Any]] = field(default_factory=dict)
    trials: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    tuned_rules: dict[str, dict[str, float]] = field(default_factory=dict)
    importance: list[dict[str, Any]] = field(default_factory=list)
    final_model: FittedModel | None = None
    final_calibrator: IsotonicCalibrator | None = None


_PREDICTION_KEYS: Final = ("account_id", "as_of", "label", "already_active", "illicit_inflow_usd")


def _predictions(
    test: pl.DataFrame,
    model: str,
    score: np.ndarray,
    probability: np.ndarray | None,
    tie: np.ndarray,
) -> pl.DataFrame:
    return test.select(_PREDICTION_KEYS).with_columns(
        model=pl.lit(model),
        score=pl.Series(score, dtype=pl.Float64),
        probability=pl.Series(probability, dtype=pl.Float64)
        if probability is not None
        else pl.lit(None, dtype=pl.Float64),
        tie_breaker=pl.Series(tie, dtype=pl.Float64),
    )


class Backtest:
    """Run the model ladder over the rolling-origin folds of one dataset."""

    def __init__(
        self,
        snapshots: pl.DataFrame,
        *,
        rules: RulesConfig,
        features: FeatureConfig,
        training: TrainingConfig,
        headline_budget: float,
        run_logger: RunLogger,
        include_rules: bool = True,
        preset_params: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.snapshots = snapshots
        self.include_rules = include_rules
        self.rules = rules
        self.features = features
        self.training = training
        self.headline_budget = headline_budget
        self.run_logger = run_logger
        self.result = BacktestResult(predictions=pl.DataFrame())
        # Preset parameters skip the search, e.g. to reuse the main backtest's choice in a sweep.
        self.result.chosen_params.update(preset_params or {})

    def _split(self, fold: Fold) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
        known = with_known_labels(self.snapshots, fold.test_at)
        train = known.filter(pl.col("as_of").is_in(fold.train_at))
        valid = known.filter(pl.col("as_of") == fold.valid_at)
        test = self.snapshots.filter(pl.col("as_of") == fold.test_at)
        return train, valid, test

    def _rules(
        self, fold: Fold, train: pl.DataFrame, valid: pl.DataFrame, test: pl.DataFrame
    ) -> list[pl.DataFrame]:
        tie = test[self.rules.tie_breaker].fill_null(0).cast(pl.Float64).to_numpy()
        hand_set = score_rules(test, self.rules)["rules_score"].cast(pl.Float64).to_numpy()
        tuned, recall = tune_rules(
            pl.concat([train, valid]), self.rules, self.training.rules_search, self.headline_budget
        )
        self.result.tuned_rules[fold.test_at.isoformat()] = {
            **{rule.name: rule.threshold for rule in tuned.rules},
            "training_recall": round(recall, 4),
        }
        tuned_scores = score_rules(test, tuned)["rules_score"].cast(pl.Float64).to_numpy()
        return [
            _predictions(test, "rules_hand_set", hand_set, None, tie),
            _predictions(test, "rules_tuned", tuned_scores, None, tie),
        ]

    def _lgbm(
        self, fold: Fold, train: pl.DataFrame, valid: pl.DataFrame, test: pl.DataFrame
    ) -> tuple[list[pl.DataFrame], dict[str, FittedModel]]:
        frames, models = [], {}
        for name, include_graph in LGBM_MODELS.items():
            names = model_features(self.features, include_graph=include_graph)
            if name not in self.result.chosen_params:
                params, trials = select_params(train, valid, names, self.training)
                self.result.chosen_params[name], self.result.trials[name] = params, trials
            model = fit(train, valid, names, self.result.chosen_params[name], self.training)
            calibrator = IsotonicCalibrator.fit(model.predict(valid), valid["label"].to_numpy())
            raw = model.predict(test)
            frames.append(_predictions(test, name, raw, calibrator.transform(raw), raw))
            models[name] = model
            self.run_logger.log(
                f"{name}@{fold.test_at:%Y-%m-%d}",
                {**model.params, "trees": model.best_iteration, "features": len(names)},
                {"train_rows": float(train.height), "train_positives": float(train["label"].sum())},
                {"model": name, "fold": fold.test_at.isoformat()},
            )
            if name == "lgbm_tabular_graph":
                self.result.final_model, self.result.final_calibrator = model, calibrator
        return frames, models

    def run(self, folds: list[Fold], importance_from: tuple[datetime, ...]) -> BacktestResult:
        """Score every model on every fold's test snapshot."""
        frames: list[pl.DataFrame] = []
        contrib_blocks = []
        for fold in folds:
            train, valid, test = self._split(fold)
            logger.info(
                "Fold %s: %d train, %d valid, %d test rows",
                fold.test_at,
                train.height,
                valid.height,
                test.height,
            )
            if self.include_rules:
                frames += self._rules(fold, train, valid, test)
            lgbm_frames, models = self._lgbm(fold, train, valid, test)
            frames += lgbm_frames
            if fold.test_at in importance_from:
                contrib_blocks.append(contributions(models["lgbm_tabular_graph"], test))
        self.result.predictions = pl.concat(frames, how="vertical")
        if contrib_blocks and self.result.final_model is not None:
            self.result.importance = global_importance(
                np.vstack(contrib_blocks), self.result.final_model.features
            )
        return self.result
