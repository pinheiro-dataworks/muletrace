"""``muletrace data …``: download, verify, prepare, simulate the Pix layer, profile."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from muletrace.cli._common import (
    PRIMARY_PERIOD_END,
    Groups,
    add_command,
    logger,
    write_generated,
)
from muletrace.data.amlworld_loader import RawDataset
from muletrace.settings import Settings

# Library imports live inside handlers so that `muletrace --help` stays fast.
# ruff: noqa: PLC0415


def _raw_datasets(args: argparse.Namespace, settings: Settings) -> list[RawDataset]:
    return [RawDataset(name, settings.raw_dir) for name in args.datasets]


def _download(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.data.download import download_missing

    downloaded = download_missing(_raw_datasets(args, settings))
    logger.info("Downloaded %d file(s).", len(downloaded))
    return 0


def _manifest(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.data.manifest import write_manifest

    files = [path for dataset in _raw_datasets(args, settings) for path in dataset.files]
    write_manifest(files, settings.manifest_path, generated_on=datetime.now(tz=UTC).date())
    logger.info("Wrote %s for %d file(s).", settings.manifest_path, len(files))
    return 0


def _verify(_: argparse.Namespace, settings: Settings) -> int:
    from muletrace.data.manifest import verify_manifest

    verified = verify_manifest(settings.manifest_path, settings.raw_dir)
    logger.info("Checksums match for %d file(s).", len(verified))
    return 0


def _prepare(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.data.prepare import prepare_dataset

    for raw in _raw_datasets(args, settings):
        prepare_dataset(raw, settings.processed_dir)
    return 0


def _simulate_pix(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.config import CONFIG_DIR, load_config
    from muletrace.data import pix_layer_simulator
    from muletrace.data.labels import LabelConfig

    config = load_config(pix_layer_simulator.SimulatorConfig, CONFIG_DIR / "simulator.yaml")
    labels = load_config(LabelConfig, CONFIG_DIR / "labels.yaml")
    reports = {}
    for name in args.datasets:
        layer = pix_layer_simulator.run(settings.processed_dir / name, config, labels)
        logger.info("%s Pix layer: %s", name, layer.calibration["counts"])
        reports[name] = layer.calibration
    write_generated("pix_layer_calibration.yaml", reports, "muletrace data simulate-pix")
    return 0


def _profile(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.data.profile import dataset_profile

    profiles = {
        name: dataset_profile(settings.processed_dir / name, primary_end=PRIMARY_PERIOD_END)
        for name in args.datasets
    }
    write_generated("data_profile.yaml", profiles, "muletrace data profile")
    return 0


def _export_pix_layer(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.data.publish import export_bundle

    manifest = export_bundle(
        [settings.processed_dir / name for name in args.datasets],
        Path("docs/pix_layer_dataset_card.md"),
        Path("data/LICENSES/CDLA-Sharing-1.0.txt"),
        settings.artifacts_dir / "publish" / "pix-layer",
    )
    logger.info("Bundled %d files for publication", len(manifest["files"]))
    return 0


def register(groups: Groups) -> None:
    """Add the ``data`` group."""
    commands = groups.add_parser("data", help="Download, verify and prepare AMLworld")
    sub = commands.add_subparsers(dest="command", required=True)
    add_command(sub, "download", _download, "Download missing raw files from Kaggle")
    add_command(sub, "manifest", _manifest, "Write data/MANIFEST.yaml from the raw files")
    add_command(sub, "verify", _verify, "Check raw files against data/MANIFEST.yaml")
    add_command(sub, "prepare", _prepare, "Convert raw files to validated Parquet tables")
    add_command(sub, "simulate-pix", _simulate_pix, "Add the seeded Pix layer to prepared data")
    add_command(sub, "profile", _profile, "Write headline statistics to docs/generated")
    add_command(sub, "export-pix-layer", _export_pix_layer, "Bundle the Pix layer for publication")
