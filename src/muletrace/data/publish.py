"""Assemble the Pix-layer dataset for publication under CDLA-Sharing-1.0.

The bundle holds, per dataset, the four simulated tables, the calibration report and an account
map that joins the layer back to the original AMLworld files (which are not re-published), plus
the dataset card, the licence text and a checksum manifest:

    <output>/README.md                  the dataset card (docs/pix_layer_dataset_card.md)
    <output>/LICENSE                    CDLA-Sharing-1.0
    <output>/MANIFEST.yaml              size and SHA-256 of every other file
    <output>/<dataset>/pix_*.parquet     pix_transfers, pix_keys, pix_dict_markings, pix_disputes
    <output>/<dataset>/account_map.parquet
    <output>/<dataset>/calibration_report.yaml
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Final

import polars as pl
import yaml

from muletrace.data.manifest import sha256_of

PIX_TABLES: Final = ("pix_transfers", "pix_keys", "pix_dict_markings", "pix_disputes")
ACCOUNT_MAP_COLUMNS: Final = ("account_id", "bank_id", "account_number")


def export_dataset(dataset_dir: Path, output_dir: Path) -> list[Path]:
    """Copy one dataset's Pix layer and write its account map; returns the written files."""
    target = output_dir / dataset_dir.name
    target.mkdir(parents=True, exist_ok=True)
    layer = dataset_dir / "pix_layer"
    written = []
    for name in (*PIX_TABLES, "calibration_report"):
        suffix = ".yaml" if name == "calibration_report" else ".parquet"
        written.append(Path(shutil.copy2(layer / f"{name}{suffix}", target / f"{name}{suffix}")))
    account_map = target / "account_map.parquet"
    pl.read_parquet(dataset_dir / "accounts.parquet", columns=list(ACCOUNT_MAP_COLUMNS)).sort(
        "account_id"
    ).write_parquet(account_map, compression="zstd")
    written.append(account_map)
    return written


def _manifest(output_dir: Path, files: list[Path]) -> dict[str, Any]:
    return {
        "files": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_of(path),
            }
            for path in sorted(files)
        ]
    }


def export_bundle(
    dataset_dirs: list[Path], card: Path, licence: Path, output_dir: Path
) -> dict[str, Any]:
    """Write the full publication bundle and return its manifest."""
    if output_dir.exists():
        if not (output_dir / "MANIFEST.yaml").is_file():
            raise FileExistsError(f"{output_dir} exists and is not a previous bundle")
        shutil.rmtree(output_dir)  # a previous bundle, rebuilt from scratch
    output_dir.mkdir(parents=True)
    files = [
        Path(shutil.copy2(card, output_dir / "README.md")),
        Path(shutil.copy2(licence, output_dir / "LICENSE")),
    ]
    for dataset_dir in dataset_dirs:
        files += export_dataset(dataset_dir, output_dir)
    manifest = _manifest(output_dir, files)
    (output_dir / "MANIFEST.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8", newline="\n"
    )
    return manifest
