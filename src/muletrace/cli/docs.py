"""``muletrace docs render``: documents whose numbers come from generated results."""

from __future__ import annotations

import argparse
from pathlib import Path

from muletrace.cli._common import GENERATED_DIR, Groups, logger
from muletrace.settings import Settings

SOURCE_DIRS = (GENERATED_DIR, Path("configs/calibration"))
# Template folder → output folder. The README lives at the repository root.
TARGETS = ((Path("docs/templates"), Path("docs")), (Path("docs/templates/root"), Path(".")))


def _render(_: argparse.Namespace, __: Settings) -> int:
    from muletrace.reporting import render_documents  # noqa: PLC0415

    written = [
        path
        for template_dir, output_dir in TARGETS
        for path in render_documents(template_dir, SOURCE_DIRS, output_dir)
    ]
    logger.info("Rendered %s", ", ".join(str(path) for path in written))
    return 0


def register(groups: Groups) -> None:
    """Add the ``docs`` group."""
    docs = groups.add_parser("docs", help="Documents rendered from generated results")
    commands = docs.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render", help="Render docs/templates into docs/ and the README")
    render.set_defaults(handler=_render)
