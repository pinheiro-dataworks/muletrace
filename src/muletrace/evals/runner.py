"""Run a copilot provider over gold cases and check the results against thresholds.

Providers:

* ``template`` — the deterministic baseline; runs anywhere, no model, no cost;
* ``single`` — one Bedrock call with all the evidence (the LLM baseline);
* ``multi`` — the three-agent copilot on Bedrock.

Bedrock providers need AWS credentials with model access; the caller passes a factory that
returns a model client for a model ID, so tests use scripted clients.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import Field

from muletrace.agents.llm import ModelClient, ModelPrice, Usage
from muletrace.agents.orchestrator import CopilotRun, run_multi_agent, run_single_call
from muletrace.agents.template import template_case_file
from muletrace.config import StrictModel
from muletrace.evals.adversarial import (
    ATTACKS,
    blocked_by_checker,
    checker_strictness,
    compromised,
    inject,
)
from muletrace.evals.gold import GoldCase
from muletrace.evals.metrics import CaseOutcome, summarise
from muletrace.validation.fact_checker import check_case_file

PROVIDERS = ("template", "single", "multi")
ClientFactory = Callable[[str], ModelClient]


class CopilotConfig(StrictModel):
    """Copilot models, prices and budgets, read from ``configs/copilot.yaml``."""

    agent_model: str
    single_call_model: str
    judge_model: str | None = None
    prices: dict[str, ModelPrice]
    price_source: str
    token_budget_per_case: int = Field(gt=0)
    max_tool_rounds: int = Field(gt=0)
    smoke_cases: int = Field(gt=0)
    adversarial_cases: int = Field(gt=0)


def run_case(
    provider: str, evidence_case: GoldCase, config: CopilotConfig, factory: ClientFactory | None
) -> CopilotRun:
    """Draft one case with one provider."""
    evidence = evidence_case.evidence
    if provider == "template":
        started = time.perf_counter()
        case_file = template_case_file(evidence)
        usage = Usage(latency_ms=(time.perf_counter() - started) * 1000)
        return CopilotRun(
            case_file=case_file, check=check_case_file(case_file, evidence), usage=usage
        )
    if factory is None:
        raise ValueError(f"provider {provider!r} needs a model client factory")
    if provider == "single":
        model = config.single_call_model
        return run_single_call(
            evidence, factory(model), config.prices.get(model), config.token_budget_per_case
        )
    model = config.agent_model
    return run_multi_agent(
        evidence,
        factory(model),
        config.prices.get(model),
        config.token_budget_per_case,
        config.max_tool_rounds,
    )


def _rejected(outcomes: list[CaseOutcome]) -> int:
    """Drafts that were parsed but stopped by the checker."""
    return sum(1 for o in outcomes if o.run.case_file and not o.run.delivered)


def _delivered_files(outcomes: list[CaseOutcome]) -> list[dict[str, Any]]:
    return [o.run.case_file.model_dump() for o in outcomes if o.run.delivered and o.run.case_file]


def _attack_report(attack: str, outcomes: list[CaseOutcome]) -> dict[str, Any]:
    return {
        "cases": len(outcomes),
        "compromised_and_delivered": sum(1 for o in outcomes if compromised(attack, o)),
        "rejected_by_checker": _rejected(outcomes),
        "checker_rules_triggered": sorted({r for o in outcomes for r in blocked_by_checker(o)}),
    }


def _adversarial(
    provider: str, cases: list[GoldCase], config: CopilotConfig, factory: ClientFactory | None
) -> dict[str, Any]:
    positives = [case for case in cases if case.is_positive][: config.adversarial_cases]
    report: dict[str, Any] = {}
    for attack in ATTACKS:
        attacked = [
            case.model_copy(update={"evidence": inject(case.evidence, attack)})
            for case in positives
        ]
        outcomes = [CaseOutcome(c, run_case(provider, c, config, factory)) for c in attacked]
        report[attack] = _attack_report(attack, outcomes)
    return report


def _model(provider: str, config: CopilotConfig) -> str | None:
    models = {"single": config.single_call_model, "multi": config.agent_model}
    return models.get(provider)


def evaluate(
    provider: str,
    cases: list[GoldCase],
    config: CopilotConfig,
    factory: ClientFactory | None = None,
) -> dict[str, Any]:
    """Metrics, checker strictness and the adversarial suite for one provider.

    ``delivered_case_files`` lists every case file that passed the checker, for human review and
    judge calibration; it is not part of the published report.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    outcomes = [CaseOutcome(case, run_case(provider, case, config, factory)) for case in cases]
    return {
        "provider": provider,
        "model": _model(provider, config),
        "metrics": summarise(outcomes),
        "checker_strictness": checker_strictness(outcomes),
        "adversarial": _adversarial(provider, cases, config, factory),
        "delivered_case_files": _delivered_files(outcomes),
    }


class EvalThresholds(StrictModel):
    """Release gates, read from ``configs/eval_thresholds.yaml``."""

    max_unsupported_claims_reaching_analyst: int = Field(ge=0)
    min_checker_rejection_rate: float = Field(ge=0, le=1)
    max_compromised_and_delivered: int = Field(ge=0)
    max_cost_per_case_usd: float = Field(gt=0)
    max_latency_seconds_p95: float = Field(gt=0)
    min_action_agreement: float = Field(ge=0, le=1)


def _component_failures(result: dict[str, Any], thresholds: EvalThresholds) -> list[str]:
    """Perturbations the checker let through and attacks that reached the analyst."""
    missed = [
        f"checker missed perturbation {name}"
        for name, row in result["checker_strictness"].items()
        if row["drafts"] and row["rejection_rate"] < thresholds.min_checker_rejection_rate
    ]
    return missed + [
        f"attack {attack} reached the analyst"
        for attack, row in result["adversarial"].items()
        if row["compromised_and_delivered"] > thresholds.max_compromised_and_delivered
    ]


def gate(result: dict[str, Any], thresholds: EvalThresholds) -> list[str]:
    """Every threshold the result fails, as readable messages (empty means pass)."""
    metrics = {key: value or 0 for key, value in result["metrics"].items()}
    first = (
        metrics["unsupported_claims_reaching_analyst"]
        > thresholds.max_unsupported_claims_reaching_analyst,
        "unsupported claims reached the analyst",
    )
    budgets = [
        (
            metrics["cost_per_case_usd_mean"] > thresholds.max_cost_per_case_usd,
            "cost per case above budget",
        ),
        (
            metrics["latency_seconds_p95"] > thresholds.max_latency_seconds_p95,
            "p95 latency above budget",
        ),
        (
            metrics["action_agreement"] < thresholds.min_action_agreement,
            "action agreement below threshold",
        ),
    ]
    head = [first[1]] if first[0] else []
    return head + _component_failures(result, thresholds) + [m for bad, m in budgets if bad]
