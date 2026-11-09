"""Turn backtest predictions into the numbers published in ``docs/eval_report.md``.

Every figure in the eval report is produced here and written to
``docs/generated/backtest_<dataset>.yaml``. The sections:

* per-fold metrics for every model (stability across the rolling origin);
* hold-out metrics pooled over the test snapshots, with paired bootstrap intervals for the
  headline budget, including the model-minus-rules and graph-minus-tabular differences;
* expected cost in review units for every assumed cost of a missed mule;
* calibration of the LightGBM probabilities;
* error slices of the best model by typology, activity status and ticket band.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

import numpy as np
import polars as pl

from muletrace.models.bootstrap import BootstrapSnapshot, bootstrap_metrics, interval
from muletrace.models.calibration import brier_score, reliability_table
from muletrace.models.cost_curve import cost_summary
from muletrace.models.evaluate import (
    EvaluationConfig,
    alert_count,
    average_precision,
    budget_table,
    top_k_mask,
)

TICKET_BANDS_USD: Final = (0.0, 1_000.0, 10_000.0, 100_000.0)
_COST_CURVE_MAX_PER_10K: Final = 200


def _ticket_band() -> pl.Expr:
    value = pl.col("illicit_inflow_usd")
    return (
        pl.when(value <= TICKET_BANDS_USD[0])
        .then(pl.lit("no illicit inflow in horizon"))
        .when(value < TICKET_BANDS_USD[1])
        .then(pl.lit("under 1k USD"))
        .when(value < TICKET_BANDS_USD[2])
        .then(pl.lit("1k to 10k USD"))
        .when(value < TICKET_BANDS_USD[3])
        .then(pl.lit("10k to 100k USD"))
        .otherwise(pl.lit("100k USD or more"))
    )


def _arrays(snapshot: pl.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    return (
        snapshot["label"].to_numpy(),
        snapshot["score"].to_numpy(),
        snapshot["illicit_inflow_usd"].to_numpy(),
        snapshot["tie_breaker"].to_numpy(),
    )


def per_fold(predictions: pl.DataFrame, evaluation: EvaluationConfig) -> dict[str, Any]:
    """Average precision and budget table for every model and test snapshot."""
    result: dict[str, Any] = {}
    for (model, as_of), snapshot in predictions.sort("model", "as_of").group_by(
        "model", "as_of", maintain_order=True
    ):
        labels, scores, values, tie = _arrays(snapshot)
        result.setdefault(str(model), {})[as_of.isoformat()] = {
            "scored_accounts": snapshot.height,
            "positives": int(labels.sum()),
            "average_precision": round(average_precision(labels, scores), 4),
            "budgets": budget_table(labels, scores, values, evaluation.alert_budgets_per_10k, tie),
        }
    return result


def pooled(
    predictions: pl.DataFrame, model: str, budgets: tuple[float, ...]
) -> list[dict[str, float]]:
    """Budget metrics summed over every snapshot of ``model`` in ``predictions``."""
    rows = []
    for budget in budgets:
        totals = np.zeros(5)
        for _, snapshot in predictions.filter(pl.col("model") == model).group_by("as_of"):
            labels, scores, values, tie = _arrays(snapshot)
            mask = top_k_mask(scores, alert_count(labels.size, budget), tie)
            totals += [
                mask.sum(),
                np.sum(labels & mask),
                labels.sum(),
                values[mask].sum(),
                values.sum(),
            ]
        alerts, hits, positives, value_hit, value_total = totals
        rows.append(
            {
                "alerts_per_10k": budget,
                "alerts": int(alerts),
                "true_positives": int(hits),
                "positives": int(positives),
                "recall": round(hits / positives, 4) if positives else 0.0,
                "precision": round(hits / alerts, 4) if alerts else 0.0,
                "value_share": round(value_hit / value_total, 4) if value_total else 0.0,
            }
        )
    return rows


def bootstrap_section(
    predictions: pl.DataFrame,
    models: list[str],
    comparisons: list[tuple[str, str]],
    evaluation: EvaluationConfig,
) -> dict[str, Any]:
    """Point estimates and 95% intervals at the headline budget, plus paired differences."""
    snapshots = []
    for _, group in predictions.sort("as_of", "model", "account_id").group_by(
        "as_of", maintain_order=True
    ):
        by_model = {name: frame.sort("account_id") for (name,), frame in group.group_by("model")}
        labels = by_model[models[0]]["label"].to_numpy()
        snapshots.append(
            BootstrapSnapshot.from_scores(
                labels,
                [by_model[m]["score"].to_numpy() for m in models],
                [by_model[m]["tie_breaker"].to_numpy() for m in models],
            )
        )
    budget = evaluation.headline_alert_budget_per_10k
    point = bootstrap_metrics(snapshots, budget, replicates=1, seed=0, poisson=False)
    samples = bootstrap_metrics(
        snapshots, budget, evaluation.bootstrap.replicates, evaluation.bootstrap.seed
    )
    section: dict[str, Any] = {
        "alerts_per_10k": budget,
        "replicates": evaluation.bootstrap.replicates,
    }
    for metric in ("recall", "average_precision"):
        section[metric] = {
            model: {
                "estimate": round(float(point[metric][i, 0]), 4),
                "ci95": interval(samples[metric][i]),
            }
            for i, model in enumerate(models)
        }
        section[f"{metric}_difference"] = {
            f"{a} minus {b}": {
                "estimate": round(
                    float(point[metric][models.index(a), 0] - point[metric][models.index(b), 0]), 4
                ),
                "ci95": interval(
                    samples[metric][models.index(a)] - samples[metric][models.index(b)]
                ),
            }
            for a, b in comparisons
        }
    return section


def cost_section(
    predictions: pl.DataFrame, models: list[str], evaluation: EvaluationConfig
) -> dict[str, Any]:
    """Expected cost per assumed missed-mule cost, summed over the hold-out snapshots."""
    result: dict[str, Any] = {}
    for model in models:
        rows = []
        for missed_cost in evaluation.missed_mule_cost_review_units:
            totals: dict[str, float] = {}
            for _, snapshot in predictions.filter(pl.col("model") == model).group_by("as_of"):
                labels, scores, _, _ = _arrays(snapshot)
                probabilities = (
                    snapshot["probability"].to_numpy()
                    if snapshot["probability"].null_count() == 0
                    else None
                )
                summary = cost_summary(
                    labels=labels,
                    scores=scores,
                    probabilities=probabilities,
                    missed_cost=missed_cost,
                    budget_alerts=alert_count(
                        labels.size, evaluation.headline_alert_budget_per_10k
                    ),
                    max_alerts=alert_count(labels.size, _COST_CURVE_MAX_PER_10K),
                )
                for key, value in summary.items():
                    totals[key] = (
                        value if key == "missed_mule_cost" else totals.get(key, 0.0) + value
                    )
            rows.append(totals)
        result[model] = rows
    return result


def calibration_section(predictions: pl.DataFrame, models: list[str]) -> dict[str, Any]:
    """Brier score of raw and calibrated scores, and the reliability table, pooled."""
    result: dict[str, Any] = {}
    for model in models:
        frame = predictions.filter(pl.col("model") == model)
        labels = frame["label"].to_numpy()
        calibrated = frame["probability"].to_numpy()
        result[model] = {
            "brier_raw": round(brier_score(frame["score"].to_numpy(), labels), 6),
            "brier_calibrated": round(brier_score(calibrated, labels), 6),
            "brier_constant_prevalence": round(
                brier_score(np.full(labels.size, labels.mean()), labels), 6
            ),
            "mean_predicted": round(float(calibrated.mean()), 6),
            "observed_rate": round(float(labels.mean()), 6),
            "reliability": reliability_table(calibrated, labels),
        }
    return result


def slice_section(
    predictions: pl.DataFrame, model: str, typology: pl.DataFrame, budget: float
) -> dict[str, Any]:
    """Recall of ``model`` at ``budget`` among positives, by typology, activity and ticket band."""
    frames = []
    for _, snapshot in predictions.filter(pl.col("model") == model).group_by("as_of"):
        labels, scores, _, tie = _arrays(snapshot)
        mask = top_k_mask(scores, alert_count(labels.size, budget), tie)
        frames.append(snapshot.with_columns(alerted=pl.Series(mask)))
    positives = (
        pl.concat(frames)
        .filter("label")
        .join(typology, on="account_id", how="left")
        .with_columns(
            typology=pl.col("typology").fill_null("no pattern"),
            activity=pl.when("already_active")
            .then(pl.lit("already active at as-of"))
            .otherwise(pl.lit("not yet active")),
            ticket_band=_ticket_band(),
        )
    )
    return {
        dimension: {
            row[dimension]: {"positives": row["positives"], "recall": round(row["recall"], 4)}
            for row in positives.group_by(dimension)
            .agg(positives=pl.len(), recall=pl.col("alerted").mean())
            .sort(dimension)
            .iter_rows(named=True)
        }
        for dimension in ("typology", "activity", "ticket_band")
    }


def holdout(predictions: pl.DataFrame, test_snapshots: tuple[datetime, ...]) -> pl.DataFrame:
    """Predictions on the hold-out snapshots only."""
    return predictions.filter(pl.col("as_of").is_in(test_snapshots))
