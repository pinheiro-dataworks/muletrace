"""``muletrace copilot …``: gold cases and the copilot evaluation gate."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import TYPE_CHECKING

from muletrace.cli._common import Groups, logger, write_generated
from muletrace.data.amlworld_loader import DATASETS
from muletrace.settings import Settings

if TYPE_CHECKING:
    from muletrace.agents.llm import ModelClient

# Library imports live inside handlers so that `muletrace --help` stays fast.
# ruff: noqa: PLC0415

GOLD_DIR = Path("evals/gold_cases")


def _gold(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.evals.gold import build_gold_cases, write_gold_cases

    cases = build_gold_cases(
        settings.processed_dir / args.dataset, args.per_typology, args.negatives, args.seed
    )
    write_gold_cases(cases, GOLD_DIR / f"{args.dataset}.jsonl")
    logger.info("Wrote %d gold cases for %s", len(cases), args.dataset)
    return 0


def _bedrock_factory(model_id: str) -> ModelClient:
    import boto3

    from muletrace.agents.llm import BedrockClient

    return BedrockClient(
        model_id=model_id,
        runtime=boto3.client("bedrock-runtime", region_name="us-east-1"),
        guardrail_id=os.environ.get("BEDROCK_GUARDRAIL_ID"),
    )


def _write_case_files(case_files: list[dict[str, object]], path: Path) -> None:
    """Keep delivered case files for human review and judge calibration (never committed)."""
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for case_file in case_files:
            handle.write(json.dumps(case_file, sort_keys=True) + "\n")
    logger.info("Wrote %d delivered case files to %s", len(case_files), path)


def _evaluate(args: argparse.Namespace, settings: Settings) -> int:
    from muletrace.config import CONFIG_DIR, load_config
    from muletrace.evals.gold import read_gold_cases
    from muletrace.evals.runner import CopilotConfig, EvalThresholds, evaluate, gate

    config = load_config(CopilotConfig, CONFIG_DIR / "copilot.yaml")
    cases = read_gold_cases(GOLD_DIR / f"{args.dataset}.jsonl")
    if args.smoke:
        cases = cases[:: max(1, len(cases) // config.smoke_cases)][: config.smoke_cases]
    factory = None if args.provider == "template" else _bedrock_factory
    result = evaluate(args.provider, cases, config, factory)
    _write_case_files(
        result.pop("delivered_case_files"),
        settings.artifacts_dir / "copilot" / f"{args.provider}_{args.dataset}.jsonl",
    )
    failures = gate(result, load_config(EvalThresholds, CONFIG_DIR / "eval_thresholds.yaml"))
    result["gate"] = {"passed": not failures, "failures": failures, "smoke": args.smoke}
    suffix = "_smoke" if args.smoke else ""
    write_generated(
        f"copilot_eval_{args.provider}_{args.dataset}{suffix}.yaml",
        result,
        "muletrace copilot eval",
    )
    for failure in failures:
        logger.error("Gate failed: %s", failure)
    return 1 if failures else 0


def register(groups: Groups) -> None:
    """Add the ``copilot`` group."""
    copilot = groups.add_parser("copilot", help="Investigation copilot: gold cases and evaluation")
    sub = copilot.add_subparsers(dest="command", required=True)
    gold = sub.add_parser("gold", help="Build gold cases from the patterns file")
    gold.add_argument("--dataset", default="HI-Small", choices=DATASETS)
    gold.add_argument("--per-typology", type=int, default=15)
    gold.add_argument("--negatives", type=int, default=30)
    gold.add_argument("--seed", type=int, default=20261113)
    gold.set_defaults(handler=_gold)
    run = sub.add_parser("eval", help="Evaluate a provider and apply the release gate")
    run.add_argument("--provider", choices=("template", "single", "multi"), default="template")
    run.add_argument("--dataset", default="HI-Small", choices=DATASETS)
    run.add_argument("--smoke", action="store_true", help="Evaluate the smoke subset only")
    run.set_defaults(handler=_evaluate)
