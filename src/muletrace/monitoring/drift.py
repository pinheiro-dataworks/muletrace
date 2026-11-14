"""Distribution drift between a reference snapshot and a current one.

Two statistics per monitored column, both computed with NumPy only so the job runs in the
batch image without SciPy:

* **PSI** (population stability index) over ten bins cut at the reference deciles. Missing
  values get a bin of their own, and empty bins are floored at a small share so the logarithm
  stays finite;
* **KS**, the two-sample Kolmogorov-Smirnov statistic (largest gap between the two empirical
  distribution functions), on non-missing values.

With hundreds of thousands of accounts any difference is "significant", so no p-value is
reported: alerts use the statistics themselves against thresholds in ``configs/monitoring.yaml``.
"""

from __future__ import annotations

from typing import Any, Final

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from muletrace.config import StrictModel

BINS: Final = 10
MIN_SHARE: Final = 1e-4


class DriftConfig(StrictModel):
    """What to monitor and when to alert, read from ``configs/monitoring.yaml``."""

    dataset: str
    reference_day: str
    features: tuple[str, ...] = Field(min_length=1, max_length=7)  # 3 + 7 = 10 metrics
    report_only: tuple[str, ...] = ()
    psi_alert: float = Field(gt=0)
    ks_alert: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def _report_only_is_monitored(self) -> DriftConfig:
        if not set(self.report_only) < set(self.features):
            raise ValueError("report_only must be a strict subset of features")
        return self

    @property
    def alerting(self) -> tuple[str, ...]:
        """Monitored features that can raise an alert."""
        return tuple(name for name in self.features if name not in self.report_only)


def _shares(values: NDArray[np.float64], edges: NDArray[np.float64]) -> NDArray[np.float64]:
    """Share of values per bin, with missing values in an extra last bin."""
    missing = np.isnan(values)
    counts = np.bincount(
        np.searchsorted(edges, values[~missing], side="right"), minlength=len(edges) + 1
    ).astype(np.float64)
    shares = np.append(counts, missing.sum()) / max(len(values), 1)
    return np.maximum(shares, MIN_SHARE)


def psi(reference: NDArray[np.float64], current: NDArray[np.float64]) -> float:
    """Population stability index of ``current`` against ``reference``."""
    observed = reference[~np.isnan(reference)]
    if observed.size == 0:
        edges = np.array([], dtype=np.float64)
    else:
        edges = np.unique(np.quantile(observed, np.linspace(0, 1, BINS + 1)[1:-1]))
    expected, actual = _shares(reference, edges), _shares(current, edges)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def ks_statistic(reference: NDArray[np.float64], current: NDArray[np.float64]) -> float:
    """Largest gap between the two empirical distribution functions (missing values dropped)."""
    left = np.sort(reference[~np.isnan(reference)])
    right = np.sort(current[~np.isnan(current)])
    if left.size == 0 or right.size == 0:
        return 0.0
    grid = np.concatenate([left, right])
    gaps = (
        np.searchsorted(left, grid, side="right") / left.size
        - np.searchsorted(right, grid, side="right") / right.size
    )
    return float(np.max(np.abs(gaps)))


def _column_drift(reference: NDArray[np.float64], current: NDArray[np.float64]) -> dict[str, float]:
    return {
        "psi": round(psi(reference, current), 4),
        "ks": round(ks_statistic(reference, current), 4),
    }


def drift_report(
    reference: dict[str, NDArray[np.float64]],
    current: dict[str, NDArray[np.float64]],
    config: DriftConfig,
) -> dict[str, Any]:
    """PSI and KS for the score and every monitored feature, and the alerts they raise.

    Features listed as ``report_only`` are measured and published but never alert, and are left
    out of ``max_feature_psi``.

    ``reference`` and ``current`` map column names to values; both must contain
    ``probability`` and every feature in the configuration.
    """
    features = {name: _column_drift(reference[name], current[name]) for name in config.features}
    score = _column_drift(reference["probability"], current["probability"])
    alerting = {name: features[name] for name in config.alerting}
    worst = max(alerting.items(), key=lambda item: item[1]["psi"])
    alerts = [
        f"{name}: {stat} {value} above {limit}"
        for name, row in {"probability": score, **alerting}.items()
        for stat, value, limit in (
            ("psi", row["psi"], config.psi_alert),
            ("ks", row["ks"], config.ks_alert),
        )
        if value > limit
    ]
    return {
        "score": score,
        "features": features,
        "max_feature_psi": {"feature": worst[0], "psi": worst[1]["psi"]},
        "alerts": alerts,
    }


def cloudwatch_metrics(report: dict[str, Any], dataset: str) -> list[dict[str, Any]]:
    """The report as CloudWatch metric data (at most ten custom metrics per dataset)."""
    dimensions = [{"Name": "Dataset", "Value": dataset}]
    metrics = [
        {"MetricName": "ScorePSI", "Value": report["score"]["psi"]},
        {"MetricName": "ScoreKS", "Value": report["score"]["ks"]},
        {"MetricName": "MaxFeaturePSI", "Value": report["max_feature_psi"]["psi"]},
    ]
    for name, row in report["features"].items():
        metrics.append(
            {
                "MetricName": "FeaturePSI",
                "Value": row["psi"],
                "Dimensions": [*dimensions, {"Name": "Feature", "Value": name}],
            }
        )
    return [{"Dimensions": dimensions, "Unit": "None", **m} for m in metrics]
