"""``muletrace docs render``: documents whose numbers come from generated results."""

from __future__ import annotations

import argparse
from pathlib import Path

from muletrace.cli._common import GENERATED_DIR, Groups, logger
from muletrace.settings import Settings

TEMPLATE_DIR = Path("docs/templates")
SOURCE_DIRS = (GENERATED_DIR, Path("configs/calibration"))


def _render(_: argparse.Namespace, __: Settings) -> int:
    from muletrace.reporting import render_documents  # noqa: PLC0415

    written = render_documents(TEMPLATE_DIR, SOURCE_DIRS, Path("docs"))
    logger.info("Rendered %s", ", ".join(str(path) for path in written))
    return 0


def register(groups: Groups) -> None:
    """Add the ``docs`` group."""
    docs = groups.add_parser("docs", help="Documents rendered from generated results")
    commands = docs.add_subparsers(dest="command", required=True)
    commands.add_parser("render", help="Render docs/templates into docs/").set_defaults(
        handler=_render
    )
