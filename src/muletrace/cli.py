"""Command-line entry point: ``muletrace <group> <command>``.

Each command is a thin adapter from arguments to a library function, so everything the CLI
does can also be called from tests, notebooks and the SageMaker job.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from muletrace.data.amlworld_loader import DATASETS, RawDataset
from muletrace.settings import Settings, load_env_file

logger = logging.getLogger("muletrace")

Handler = Callable[[argparse.Namespace, Settings], int]


def _raw_datasets(args: argparse.Namespace, settings: Settings) -> list[RawDataset]:
    return [RawDataset(name, settings.raw_dir) for name in args.datasets]


def _data_download(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.data.download import download_missing  # noqa: PLC0415 - keeps CLI start fast

    downloaded = download_missing(_raw_datasets(args, settings))
    logger.info("Downloaded %d file(s).", len(downloaded))
    return 0


def _data_manifest(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.data.manifest import write_manifest  # noqa: PLC0415

    files = [path for dataset in _raw_datasets(args, settings) for path in dataset.files]
    write_manifest(files, settings.manifest_path, generated_on=datetime.now(tz=UTC).date())
    logger.info("Wrote %s for %d file(s).", settings.manifest_path, len(files))
    return 0


def _data_verify(_: argparse.Namespace, settings: Settings) -> int:
    from muletrace.data.manifest import verify_manifest  # noqa: PLC0415

    verified = verify_manifest(settings.manifest_path, settings.raw_dir)
    logger.info("Checksums match for %d file(s).", len(verified))
    return 0


def _data_prepare(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.data.prepare import prepare_dataset  # noqa: PLC0415

    for raw in _raw_datasets(args, settings):
        prepare_dataset(raw, settings.processed_dir)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with every command group."""
    parser = argparse.ArgumentParser(prog="muletrace", description=__doc__)
    groups = parser.add_subparsers(dest="group", required=True)

    data = groups.add_parser("data", help="Download, verify and prepare AMLworld")
    data_commands = data.add_subparsers(dest="command", required=True)
    for name, handler, help_text in (
        ("download", _data_download, "Download missing raw files from Kaggle"),
        ("manifest", _data_manifest, "Write data/MANIFEST.yaml from the raw files"),
        ("verify", _data_verify, "Check raw files against data/MANIFEST.yaml"),
        ("prepare", _data_prepare, "Convert raw files to validated Parquet tables"),
    ):
        command = data_commands.add_parser(name, help=help_text)
        command.add_argument("--datasets", nargs="+", default=list(DATASETS), choices=DATASETS)
        command.set_defaults(handler=handler)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, configure logging and run the selected command."""
    load_env_file()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    return handler(args, Settings.from_env())


if __name__ == "__main__":
    raise SystemExit(main())
