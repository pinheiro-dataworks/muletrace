"""Error-analysis helpers behind ``notebooks/02_error_analysis.ipynb``.

They read what the backtest already produced (the generated report, the saved predictions, the
model artefact and the cached snapshots) and never retrain anything.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from muletrace.models.artifact import ModelArtifact
from muletrace.models.evaluate import alert_count, top_k_mask
from muletrace.models.explain import booster_contributions, reason_codes


def slices_frame(report: dict[str, Any], model: str) -> pl.DataFrame:
    """Recall at the headline budget by slice, as one long table."""
    rows = [
        {"dimension": dimension, "slice": name, **values}
        for dimension, slices in report[f"slices_{model}"].items()
        for name, values in slices.items()
    ]
    return pl.DataFrame(rows).sort("dimension", "positives", descending=[False, True])


def importance_frame(report: dict[str, Any], top: int = 15) -> pl.DataFrame:
    """Mean absolute SHAP contribution of the most important features."""
    return pl.DataFrame(report["feature_importance_lgbm_tabular_graph"][:top])


def alerted(predictions: pl.DataFrame, model: str, alerts_per_10k: float) -> pl.DataFrame:
    """Add ``alerted`` to one model's predictions, snapshot by snapshot."""
    frames = []
    for _, snapshot in predictions.filter(pl.col("model") == model).group_by("as_of"):
        mask = top_k_mask(
            snapshot["score"].to_numpy(),
            alert_count(snapshot.height, alerts_per_10k),
            snapshot["tie_breaker"].to_numpy(),
        )
        frames.append(snapshot.with_columns(alerted=pl.Series(mask)))
    return pl.concat(frames).sort("as_of", "account_id")


def caught_versus_missed(
    flagged: pl.DataFrame, snapshots: pl.DataFrame, columns: list[str]
) -> pl.DataFrame:
    """Median features of positives the model alerted on against those it missed."""
    positives = flagged.filter("label").join(snapshots, on=["account_id", "as_of"], how="left")
    return (
        positives.group_by(
            outcome=pl.when("alerted").then(pl.lit("caught")).otherwise(pl.lit("missed"))
        )
        .agg(pl.len().alias("positives"), *(pl.col(c).median() for c in columns))
        .sort("outcome")
    )


def top_alert_reasons(
    artifact: ModelArtifact, snapshot: pl.DataFrame, alerts: int, top: int = 3
) -> pl.DataFrame:
    """The highest-scored accounts of a snapshot with their top SHAP reason codes."""
    _, probability = artifact.score_frame(snapshot)
    order = np.argsort(-probability, kind="stable")[:alerts]
    chosen = snapshot.select(pl.all().gather(order))
    contrib = booster_contributions(artifact.booster, artifact.features, chosen)
    codes = reason_codes(contrib, chosen, artifact.features, top=top)
    return chosen.select("account_id", "label").with_columns(
        probability=pl.Series(probability[order]),
        reasons=pl.Series(
            ["; ".join(f"{c['feature']}={c['value']:.3g}" for c in row) for row in codes]
        ),
    )
