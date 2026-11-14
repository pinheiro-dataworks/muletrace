from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from muletrace.config import CONFIG_DIR, load_config
from muletrace.monitoring.drift import (
    DriftConfig,
    cloudwatch_metrics,
    drift_report,
    ks_statistic,
    psi,
)
from muletrace.monitoring.job import NAMESPACE, drift_step

CONFIG = DriftConfig(
    dataset="HI-Small",
    reference_day="2022-09-06",
    features=("a", "b"),
    report_only=("b",),
    psi_alert=0.25,
    ks_alert=0.1,
)
RNG = np.random.default_rng(0)
values = st.lists(
    st.one_of(st.floats(-1e6, 1e6, allow_nan=False), st.just(float("nan"))),
    min_size=1,
    max_size=200,
)


def test_identical_distributions_do_not_drift() -> None:
    sample = RNG.normal(size=5_000)
    assert psi(sample, sample.copy()) == pytest.approx(0.0, abs=1e-12)
    assert ks_statistic(sample, sample.copy()) == 0.0


def test_a_shift_is_detected_and_grows_with_its_size() -> None:
    reference = RNG.normal(size=20_000)
    small, large = reference + 0.1, reference + 1.0
    assert 0 < psi(reference, small) < psi(reference, large)
    assert ks_statistic(reference, large) > ks_statistic(reference, small) > 0


def test_missing_values_have_their_own_bin() -> None:
    reference = np.array([1.0, 2.0, 3.0, 4.0])
    assert psi(reference, np.array([np.nan] * 4)) > 1
    assert psi(np.array([np.nan, np.nan]), np.array([np.nan, np.nan])) == 0.0
    assert ks_statistic(np.array([np.nan]), reference) == 0.0


def test_disjoint_samples_have_ks_one() -> None:
    assert ks_statistic(np.array([1.0, 2.0]), np.array([10.0, 11.0])) == 1.0


@settings(max_examples=80, deadline=None)
@given(reference=values, current=values)
def test_psi_is_never_negative_and_ks_stays_in_range(
    reference: list[float], current: list[float]
) -> None:
    left, right = np.array(reference), np.array(current)
    assert psi(left, right) >= -1e-12
    assert 0.0 <= ks_statistic(left, right) <= 1.0


def test_report_only_features_are_measured_but_never_alert() -> None:
    base = RNG.normal(size=2_000)
    reference = {"a": base, "b": base, "probability": base}
    current = {"a": base, "b": base + 10, "probability": base + 10}
    report = drift_report(reference, current, CONFIG)
    assert report["features"]["b"]["psi"] > CONFIG.psi_alert
    assert report["max_feature_psi"]["feature"] == "a"
    assert report["alerts"] == [
        f"probability: psi {report['score']['psi']} above 0.25",
        f"probability: ks {report['score']['ks']} above 0.1",
    ]


def test_configuration_rules() -> None:
    shipped = load_config(DriftConfig, CONFIG_DIR / "monitoring.yaml")
    assert len(shipped.features) + 3 <= 10  # CloudWatch custom-metric budget
    assert "account_age_hours" in shipped.report_only
    with pytest.raises(ValidationError, match="strict subset"):
        CONFIG.model_validate({**CONFIG.model_dump(), "report_only": ["a", "b"]})


def test_cloudwatch_metrics() -> None:
    base = RNG.normal(size=100)
    report = drift_report(
        {"a": base, "b": base, "probability": base},
        {"a": base, "b": base, "probability": base},
        CONFIG,
    )
    metrics = cloudwatch_metrics(report, "HI-Small")
    assert [m["MetricName"] for m in metrics] == [
        "ScorePSI",
        "ScoreKS",
        "MaxFeaturePSI",
        "FeaturePSI",
        "FeaturePSI",
    ]
    assert metrics[3]["Dimensions"] == [
        {"Name": "Dataset", "Value": "HI-Small"},
        {"Name": "Feature", "Value": "a"},
    ]


class FakeS3:
    def __init__(self, frames: dict[str, pl.DataFrame]) -> None:
        self.frames = frames
        self.objects: dict[str, bytes] = {}

    def download_file(self, _bucket: str, key: str, path: str) -> None:
        self.frames[key].write_parquet(path)

    def put_object(self, **kwargs: object) -> None:
        self.objects[str(kwargs["Key"])] = kwargs["Body"]  # type: ignore[assignment]


class FakeCloudWatch:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def put_metric_data(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def _day(day: str, shift: float) -> dict[str, pl.DataFrame]:
    shipped = load_config(DriftConfig, CONFIG_DIR / "monitoring.yaml")
    accounts = list(range(500))
    noise = np.random.default_rng(1).normal(size=500) + shift
    snapshot = pl.DataFrame(
        {"account_id": accounts, **dict.fromkeys(shipped.features, noise)}
    ).with_columns(as_of=pl.lit(datetime.fromisoformat(day)))
    scores = pl.DataFrame({"account_id": accounts, "probability": 1 / (1 + np.exp(-noise))})
    return {
        f"snapshots/HI-Small/{day}.parquet": snapshot,
        f"scores/HI-Small/{day}.parquet": scores,
    }


def test_drift_step_publishes_metrics_and_stores_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    s3 = FakeS3({**_day("2022-09-06", 0.0), **_day("2022-09-09", 2.0)})
    cloudwatch = FakeCloudWatch()
    report = drift_step({"current_day": "2022-09-09"}, s3, cloudwatch, tmp_path)
    assert report["reference_day"] == "2022-09-06"
    assert report["report_only"] == ["account_age_hours"]
    assert any(alert.startswith("probability: psi") for alert in report["alerts"])
    assert cloudwatch.calls[0]["Namespace"] == NAMESPACE
    assert list(s3.objects) == ["monitoring/drift/HI-Small/2022-09-09.json"]
