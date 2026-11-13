"""``muletrace trace …``: fund-flow tracing of disputed transfers."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import yaml

from muletrace.cli._common import Groups, add_command, write_generated
from muletrace.data.amlworld_loader import DATASETS
from muletrace.serialization import to_builtin
from muletrace.settings import Settings

if TYPE_CHECKING:
    from muletrace.tracing.med_tracer import TracerConfig

# Library imports live inside handlers so that `muletrace --help` stays fast.
# ruff: noqa: PLC0415


def tracer_config() -> TracerConfig:
    """Tracing parameters from ``configs/tracer.yaml``."""
    from muletrace.config import CONFIG_DIR, load_config
    from muletrace.tracing.med_tracer import TracerConfig

    return load_config(TracerConfig, CONFIG_DIR / "tracer.yaml")


def _evaluate(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.tracing.evaluate import evaluate_tracer

    config = tracer_config()
    for name in args.datasets:
        result = evaluate_tracer(settings.processed_dir / name, config)
        write_generated(f"tracer_evaluation_{name}.yaml", result, "muletrace trace evaluate")
    return 0


def _show(args: argparse.Namespace, settings: Settings) -> int:
    import polars as pl

    from muletrace.tracing.med_tracer import trace

    transactions = pl.scan_parquet(settings.processed_dir / args.dataset / "transactions.parquet")
    result = trace(transactions, args.tx_id, tracer_config())
    print(yaml.safe_dump(to_builtin(result.summary()), sort_keys=False))
    return 0


def register(groups: Groups) -> None:
    """Add the ``trace`` group."""
    tracing = groups.add_parser("trace", help="Fund-flow tracing of disputed transfers")
    sub = tracing.add_subparsers(dest="command", required=True)
    add_command(sub, "evaluate", _evaluate, "Trace every accepted dispute and score the traces")
    show = sub.add_parser("show", help="Trace one transfer and print the summary")
    show.add_argument("--dataset", default="HI-Small", choices=DATASETS)
    show.add_argument("--tx-id", type=int, required=True)
    show.set_defaults(handler=_show)
