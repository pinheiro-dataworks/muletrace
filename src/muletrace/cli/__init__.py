"""Command-line entry point: ``muletrace <group> <command>``.

Each command is a thin adapter from arguments to a library function, so everything the CLI
does can also be called from tests, notebooks and cloud jobs. Groups live in their own modules
and register themselves on the parser.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from muletrace.cli import copilot, data, docs, models, tracing
from muletrace.cli._common import Handler, logger
from muletrace.perf import measure
from muletrace.settings import Settings, load_env_file

GROUPS = (data, models, tracing, copilot, docs)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with every command group."""
    parser = argparse.ArgumentParser(prog="muletrace", description=__doc__)
    groups = parser.add_subparsers(dest="group", required=True)
    for group in GROUPS:
        group.register(groups)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, configure logging and run the selected command."""
    load_env_file()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    with measure() as measurement:
        status = handler(args, Settings.from_env())
    logger.info(
        "%s %s finished in %.1f s, peak memory %.0f MiB",
        args.group,
        args.command,
        measurement.seconds,
        measurement.peak_memory_mb,
    )
    return status


__all__ = ["build_parser", "main"]
