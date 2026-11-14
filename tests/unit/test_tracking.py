import json
import sys
import types
from pathlib import Path

import pytest

from muletrace.tracking import RunLogger


def test_local_log_appends_json_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    run_logger = RunLogger("unit", tmp_path)
    run_logger.log("first", {"a": 1}, {"m": 0.5})
    run_logger.log("second", {"a": 2}, {"m": 0.7}, {"k": "v"})
    lines = [json.loads(line) for line in (tmp_path / "unit.jsonl").read_text("utf-8").splitlines()]
    assert [line["run_name"] for line in lines] == ["first", "second"]
    assert lines[1]["tags"] == {"k": "v"}


def test_mlflow_is_used_when_a_tracking_uri_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, object]] = []

    class _Run:
        def __enter__(self) -> None:
            calls.append(("start", None))

        def __exit__(self, *_: object) -> None:
            calls.append(("end", None))

    fake = types.SimpleNamespace(
        set_experiment=lambda name: calls.append(("experiment", name)),
        start_run=lambda **_: _Run(),
        log_params=lambda params: calls.append(("params", params)),
        log_metrics=lambda metrics: calls.append(("metrics", metrics)),
    )
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    monkeypatch.setenv(
        "MLFLOW_TRACKING_URI", "arn:aws:sagemaker:us-east-1:000000000000:mlflow-app/x"
    )
    RunLogger("unit", tmp_path).log("run", {"a": 1}, {"m": 0.5})
    assert ("experiment", "unit") in calls
    assert ("params", {"a": "1"}) in calls
    assert not (tmp_path / "unit.jsonl").exists()
