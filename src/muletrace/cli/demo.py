"""``muletrace demo …``: precompute the cases shown by the static demo."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Final

from muletrace.cli._common import Groups, logger
from muletrace.settings import Settings

# Library imports live inside handlers so that `muletrace --help` stays fast.
# ruff: noqa: PLC0415

DEMO_DATA: Final = Path("demo/cases.json")
HOLD_OUT: Final = (datetime(2022, 9, 7), datetime(2022, 9, 8), datetime(2022, 9, 9))


def _build(args: argparse.Namespace, settings: Settings) -> int:
    import polars as pl

    from muletrace.cli.models import experiment_config
    from muletrace.cli.tracing import tracer_config
    from muletrace.demo.cases import DemoBuilder
    from muletrace.features.build import build_snapshots
    from muletrace.models.artifact import load_artifact
    from muletrace.serialization import to_builtin

    dataset_dir = settings.processed_dir / args.dataset
    experiment = experiment_config()
    builder = DemoBuilder(
        dataset=args.dataset,
        transactions=pl.scan_parquet(dataset_dir / "transactions.parquet"),
        descriptions=pl.read_parquet(
            dataset_dir / "pix_layer" / "pix_transfers.parquet", columns=["tx_id", "description"]
        ),
        snapshots=build_snapshots(
            dataset_dir,
            settings.features_dir,
            list(HOLD_OUT),
            experiment.labels,
            experiment.features,
        ),
        artifact=load_artifact(settings.artifacts_dir / "models" / args.dataset),
        tracer=tracer_config(),
        budget_per_10k=experiment.evaluation.headline_alert_budget_per_10k,
    )
    disputes = pl.read_parquet(dataset_dir / "pix_layer" / "pix_disputes.parquet")
    selected = [
        *builder.alerted(HOLD_OUT[-1], args.alerted),
        *builder.disputed(disputes, HOLD_OUT[0], HOLD_OUT[-1], args.disputed),
    ]
    cases = [
        builder.case(f"demo-{index:02d}", account_id, as_of, tx_id)
        for index, (account_id, as_of, tx_id) in enumerate(selected, start=1)
    ]
    payload = {
        "dataset": args.dataset,
        "synthetic": True,
        "generated_by": "muletrace demo build",
        "alert_budget_per_10k": experiment.evaluation.headline_alert_budget_per_10k,
        "cases": cases,
    }
    DEMO_DATA.parent.mkdir(parents=True, exist_ok=True)
    DEMO_DATA.write_text(
        json.dumps(to_builtin(payload), indent=1, sort_keys=False, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    logger.info("Wrote %d demo cases to %s", len(cases), DEMO_DATA)
    return 0


def register(groups: Groups) -> None:
    """Add the ``demo`` group."""
    demo = groups.add_parser("demo", help="Static demo: precomputed cases")
    sub = demo.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Score, trace and draft the demo cases")
    build.add_argument("--dataset", default="HI-Small")
    build.add_argument("--alerted", type=int, default=8, help="Alerted accounts to include")
    build.add_argument("--disputed", type=int, default=4, help="Disputed accounts to include")
    build.set_defaults(handler=_build)
