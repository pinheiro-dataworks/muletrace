"""Rules baseline: hand-set threshold rules scored on point-in-time snapshots.

The baseline is what a mid-size provider might run today: fan-in, fast pass-through, young
accounts and newly registered keys. Each triggered rule adds points; accounts are ranked by
points, with ties broken by recent inflow. The thresholds live in ``configs/rules.yaml`` and are
not tuned on the test snapshots, so the comparison with the model is honest in the rules'
favour only if the model is held to the same split.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import polars as pl
from pydantic import Field

from muletrace.config import StrictModel
from muletrace.data.labels import LabelConfig, confirmations, mule_events
from muletrace.features.account_features import account_age_hours, first_seen, flow_aggregates
from muletrace.features.asof import illicit_inflow_in_horizon, labels_at, scored_population
from muletrace.models.evaluate import EvaluationConfig, average_precision, budget_table

_RULE_WINDOW = timedelta(hours=24)
_SECONDS_PER_DAY = 86_400


class Rule(StrictModel):
    """One threshold rule."""

    name: str
    description: str
    feature: str
    operator: Literal[">=", "<="]
    threshold: float
    points: int = Field(gt=0)

    def triggered(self) -> pl.Expr:
        """Boolean expression; a missing feature value never triggers the rule."""
        value = pl.col(self.feature)
        condition = value >= self.threshold if self.operator == ">=" else value <= self.threshold
        return condition.fill_null(value=False).alias(f"rule_{self.name}")


class RulesConfig(StrictModel):
    """Rules and tie-breaker, read from ``configs/rules.yaml``."""

    tie_breaker: str
    rules: tuple[Rule, ...] = Field(min_length=1)


def rule_features(
    transactions: pl.LazyFrame,
    population: pl.DataFrame,
    first_seen_table: pl.DataFrame,
    keys: pl.DataFrame,
    as_of: datetime,
) -> pl.DataFrame:
    """Join the inputs every rule needs onto the scored population."""
    flows = flow_aggregates(transactions, as_of, _RULE_WINDOW).collect()
    key_age = keys.select(
        "account_id",
        key_age_days=(pl.lit(as_of) - pl.col("registered_at")).dt.total_seconds()
        / _SECONDS_PER_DAY,
    )
    return (
        population.join(flows, on="account_id", how="left")
        .join(account_age_hours(first_seen_table, as_of), on="account_id", how="left")
        .join(key_age, on="account_id", how="left")
    )


def score_rules(features: pl.DataFrame, config: RulesConfig) -> pl.DataFrame:
    """Add one boolean column per rule and ``rules_score``, the sum of triggered points."""
    flagged = features.with_columns(rule.triggered() for rule in config.rules)
    points = sum(
        (pl.col(f"rule_{rule.name}").cast(pl.Int32) * rule.points for rule in config.rules),
        start=pl.lit(0, dtype=pl.Int32),
    )
    return flagged.with_columns(rules_score=points)


def _snapshot_result(
    scored: pl.DataFrame, tie_breaker: str, evaluation: EvaluationConfig
) -> dict[str, Any]:
    labels = scored["label"].to_numpy()
    scores = scored["rules_score"].cast(pl.Float64).to_numpy()
    return {
        "scored_accounts": scored.height,
        "positives": int(labels.sum()),
        "average_precision": round(average_precision(labels, scores), 4),
        "budgets": budget_table(
            labels,
            scores,
            scored["illicit_inflow_usd"].to_numpy(),
            evaluation.alert_budgets_per_10k,
            tie_breaker=scored[tie_breaker].fill_null(0).cast(pl.Float64).to_numpy(),
        ),
        "rule_hit_rates": {
            column: round(float(np.mean(scored[column].to_numpy())), 4) if scored.height else 0.0
            for column in scored.columns
            if column.startswith("rule_")
        },
    }


def evaluate_rules(
    dataset_dir: Path, labels: LabelConfig, rules: RulesConfig, evaluation: EvaluationConfig
) -> dict[str, Any]:
    """Score the rules on every test snapshot of a prepared dataset."""
    transactions = pl.scan_parquet(dataset_dir / "transactions.parquet")
    keys = pl.read_parquet(dataset_dir / "pix_layer" / "pix_keys.parquet")
    confirmed = confirmations(mule_events(transactions), labels.confirmation_delay)
    first_seen_table = first_seen(transactions)
    snapshots: dict[str, Any] = {}
    for as_of in evaluation.test_snapshots:
        population = scored_population(transactions, confirmed, as_of, labels.population_lookback)
        population = labels_at(population, confirmed, as_of, labels.horizon)
        population = illicit_inflow_in_horizon(transactions, population, as_of, labels.horizon)
        features = rule_features(transactions, population, first_seen_table, keys, as_of)
        snapshots[as_of.isoformat()] = _snapshot_result(
            score_rules(features, rules), rules.tie_breaker, evaluation
        )
    return {"label_config": labels.model_dump(), "snapshots": snapshots}
