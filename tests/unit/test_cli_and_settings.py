import os
import shutil
from pathlib import Path

import polars as pl
import pytest
import yaml

from muletrace import cli
from muletrace.data import download
from muletrace.data.amlworld_loader import RawDataset
from muletrace.settings import Settings, load_env_file
from tests.fixtures.amlworld import write_amlworld_files

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    write_amlworld_files(tmp_path / "raw")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MULETRACE_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("MULETRACE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MULETRACE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    return tmp_path


def test_env_file_fills_but_never_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nMT_A='one'\nMT_B=two\nnot a pair\n\n", encoding="utf-8")
    monkeypatch.setenv("MT_B", "already set")
    monkeypatch.delenv("MT_A", raising=False)
    load_env_file(env_file)
    assert os.environ["MT_A"] == "one"
    assert os.environ["MT_B"] == "already set"
    load_env_file(tmp_path / "missing.env")


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MULETRACE_RAW_DIR", "MULETRACE_DATA_DIR", "MULETRACE_ARTIFACTS_DIR"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.raw_dir == Path("data/raw")
    assert settings.processed_dir == Path("data/processed")
    assert settings.manifest_path == Path("data/MANIFEST.yaml")
    assert settings.artifacts_dir == Path("artifacts")
    assert settings.features_dir == Path("artifacts/features")


def test_cli_manifest_verify_and_prepare(workspace: Path) -> None:
    assert cli.main(["data", "manifest", "--datasets", "HI-Small"]) == 0
    assert cli.main(["data", "verify"]) == 0
    assert cli.main(["data", "prepare", "--datasets", "HI-Small"]) == 0
    transactions = pl.read_parquet(workspace / "data/processed/HI-Small/transactions.parquet")
    assert transactions.height == 7


@pytest.mark.usefixtures("workspace")
def test_cli_download_skips_present_files() -> None:
    assert cli.main(["data", "download", "--datasets", "HI-Small"]) == 0


def test_download_calls_kaggle_for_missing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(download.shutil, "which", lambda _: "/usr/bin/kaggle")
    monkeypatch.setattr(download.subprocess, "run", lambda argv, **_: calls.append(argv))
    fetched = download.download_missing([RawDataset("LI-Small", tmp_path)])
    assert [path.name for path in fetched] == [
        "LI-Small_Trans.csv",
        "LI-Small_accounts.csv",
        "LI-Small_Patterns.txt",
    ]
    assert calls[0][:4] == ["/usr/bin/kaggle", "datasets", "download", download.KAGGLE_DATASET]


def test_download_requires_the_kaggle_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download.shutil, "which", lambda _: None)
    with pytest.raises(download.KaggleCliNotFoundError):
        download.download_missing([RawDataset("LI-Small", tmp_path)])


def test_cli_simulate_pix_after_prepare(workspace: Path) -> None:
    shutil.copytree(REPO_ROOT / "configs", workspace / "configs")
    assert cli.main(["data", "prepare", "--datasets", "HI-Small"]) == 0
    assert cli.main(["data", "simulate-pix", "--datasets", "HI-Small"]) == 0
    assert (workspace / "data/processed/HI-Small/pix_layer/calibration_report.yaml").is_file()
    assert (workspace / "docs/generated/pix_layer_calibration.yaml").is_file()
    assert cli.main(["data", "profile", "--datasets", "HI-Small"]) == 0
    profile = yaml.safe_load((workspace / "docs/generated/data_profile.yaml").read_text("utf-8"))
    assert profile["HI-Small"]["transactions"] == 7
    assert profile["HI-Small"]["pattern_share_of_laundering"] == 1.0
    assert cli.main(["models", "rules", "--datasets", "HI-Small"]) == 0
    rules = yaml.safe_load((workspace / "docs/generated/rules_baseline.yaml").read_text("utf-8"))
    assert set(rules["HI-Small"]["snapshots"]) == {
        "2022-09-07T00:00:00",
        "2022-09-08T00:00:00",
        "2022-09-09T00:00:00",
    }
    assert cli.main(["features", "build", "--datasets", "HI-Small"]) == 0
    cached = list((workspace / "artifacts" / "features").glob("HI-Small-*/*.parquet"))
    assert len(cached) == 8


def test_model_commands_write_their_reports(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from muletrace.models import experiment, transaction_level  # noqa: PLC0415

    shutil.copytree(REPO_ROOT / "configs", workspace / "configs")
    seen: dict[str, object] = {}
    monkeypatch.setattr(experiment, "run_experiment", lambda *_: {"chosen_params": {"m": {}}})
    monkeypatch.setattr(
        experiment, "run_delay_sweep", lambda *a: seen.setdefault("delays", a[3]) and {"ok": 1}
    )
    monkeypatch.setattr(transaction_level, "run_transaction_check", lambda *_: {"f1": 1.0})
    (workspace / "data/processed/HI-Small").mkdir(parents=True)
    for name in ("transactions", "accounts"):
        pl.DataFrame({"x": [1]}).write_parquet(
            workspace / f"data/processed/HI-Small/{name}.parquet"
        )

    assert cli.main(["models", "backtest", "--datasets", "HI-Small"]) == 0
    assert cli.main(["models", "delay-sweep", "--delays", "0", "24"]) == 0
    assert cli.main(["models", "transaction-check", "--datasets", "HI-Small"]) == 0
    generated = workspace / "docs/generated"
    assert {p.name for p in generated.iterdir()} >= {
        "backtest_HI-Small.yaml",
        "delay_sweep_HI-Small.yaml",
        "transaction_level_check.yaml",
    }
    assert seen["delays"] == (0, 24)


def test_trace_commands(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copytree(REPO_ROOT / "configs", workspace / "configs")
    assert cli.main(["data", "prepare", "--datasets", "HI-Small"]) == 0
    assert cli.main(["data", "simulate-pix", "--datasets", "HI-Small"]) == 0
    assert cli.main(["trace", "show", "--tx-id", "2"]) == 0
    assert "disputed_tx_id: 2" in capsys.readouterr().out
    assert cli.main(["trace", "evaluate", "--datasets", "HI-Small"]) == 0
    report = yaml.safe_load(
        (workspace / "docs/generated/tracer_evaluation_HI-Small.yaml").read_text("utf-8")
    )
    assert report["disputes_traced"] >= 0


def test_docs_render_command(monkeypatch: pytest.MonkeyPatch) -> None:
    from muletrace import reporting  # noqa: PLC0415

    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(reporting, "render_documents", lambda *args: calls.append(args) or [])
    assert cli.main(["docs", "render"]) == 0
    assert calls[0][0] == Path("docs/templates")
