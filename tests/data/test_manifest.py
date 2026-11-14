from datetime import date
from pathlib import Path

import pytest
import yaml

from muletrace.data.manifest import (
    ManifestMismatchError,
    count_data_rows,
    verify_manifest,
    write_manifest,
)
from tests.fixtures.amlworld import write_amlworld_files


def test_manifest_round_trip(tmp_path: Path) -> None:
    raw_dir = write_amlworld_files(tmp_path / "raw")
    files = sorted(raw_dir.iterdir())
    manifest_path = tmp_path / "MANIFEST.yaml"
    write_manifest(files, manifest_path, generated_on=date(2026, 11, 8))

    written = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert written["source"]["licence"] == "CDLA-Sharing-1.0"
    assert {record["name"] for record in written["files"]} == {path.name for path in files}
    trans = next(r for r in written["files"] if r["name"].endswith("_Trans.csv"))
    assert trans["data_rows"] == 7
    assert len(trans["sha256"]) == 64
    assert verify_manifest(manifest_path, raw_dir) == [r["name"] for r in written["files"]]


def test_manifest_detects_changed_and_missing_files(tmp_path: Path) -> None:
    raw_dir = write_amlworld_files(tmp_path / "raw")
    manifest_path = tmp_path / "MANIFEST.yaml"
    write_manifest(sorted(raw_dir.iterdir()), manifest_path, generated_on=date(2026, 11, 8))

    patterns = raw_dir / "HI-Small_Patterns.txt"
    patterns.write_text(patterns.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ManifestMismatchError, match="checksum"):
        verify_manifest(manifest_path, raw_dir)

    patterns.unlink()
    with pytest.raises(ManifestMismatchError, match="missing"):
        verify_manifest(manifest_path, raw_dir)


def test_count_data_rows_excludes_header(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    assert count_data_rows(path) == 2
