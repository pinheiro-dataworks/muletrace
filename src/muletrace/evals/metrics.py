"""Copilot metrics over a set of gold cases.

Two rates matter most and are kept apart on purpose:

* the **unsupported-claim rate before the checker**: the share of drafted claims that fail at
  least one fact-checking rule, which measures how often the drafting step makes things up;
* the **unsupported claims that reach the analyst**: claims in drafts that passed the checker and
  still fail a rule. The checker makes this zero by construction; it is measured anyway, so a
  regression in the checker would show up here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from muletrace.agents.case import CaseFile
from muletrace.agents.orchestrator import CopilotRun
from muletrace.evals.gold import GoldCase
from muletrace.validation.fact_checker import CheckResult, check_case_file

MIN_CLAIMS_FOR_COMPLETENESS = 3


@dataclass(frozen=True)
class CaseOutcome:
    """A gold case and the copilot's run on it."""

    case: GoldCase
    run: CopilotRun


def _complete(outcome: CaseOutcome) -> bool:
    case_file = outcome.run.case_file
    return bool(
        case_file is not None
        and case_file.summary.strip()
        and len(case_file.claims) >= MIN_CLAIMS_FOR_COMPLETENESS
        and case_file.policy_refs
        and outcome.run.check is not None
        and not any(
            v.rule in {"unknown_typology", "unknown_action"} for v in outcome.run.check.violations
        )
    )


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _parsed(outcomes: Sequence[CaseOutcome]) -> list[tuple[CaseOutcome, CaseFile, CheckResult]]:
    """Outcomes whose draft was parsed and checked, with the draft and the check result."""
    return [
        (o, o.run.case_file, o.run.check)
        for o in outcomes
        if o.run.case_file is not None and o.run.check is not None
    ]


def _claim_counts(outcomes: Sequence[CaseOutcome]) -> dict[str, int]:
    parsed = _parsed(outcomes)
    delivered = [(o, case_file) for o, case_file, _ in parsed if o.run.delivered]
    return {
        "claims": sum(check.claims for _, _, check in parsed),
        "unsupported": sum(check.unsupported_claims for _, _, check in parsed),
        "delivered_unsupported": sum(
            check_case_file(case_file, o.case.evidence).unsupported_claims
            for o, case_file in delivered
        ),
        "cited": sum(
            sum(1 for claim in case_file.claims if claim.tx_ids) for _, case_file, _ in parsed
        ),
    }


def _relevant_recall(outcomes: Sequence[CaseOutcome]) -> float | None:
    hits = total = 0
    for outcome in outcomes:
        if not outcome.case.is_positive or outcome.run.case_file is None:
            continue
        cited = {tx for claim in outcome.run.case_file.claims for tx in claim.tx_ids}
        relevant = set(outcome.case.relevant_tx_ids)
        hits += len(cited & relevant)
        total += len(relevant)
    return _ratio(hits, total)


def _typology_accuracy(drafted: list[tuple[CaseOutcome, CaseFile]]) -> float | None:
    positives = [(o, case_file) for o, case_file in drafted if o.case.is_positive]
    hits = sum(1 for o, case_file in positives if case_file.typology == o.case.typology)
    return _ratio(hits, len(positives))


def _action_agreement(drafted: list[tuple[CaseOutcome, CaseFile]]) -> float | None:
    hits = sum(
        1 for o, case_file in drafted if case_file.recommended_action in o.case.expected_actions
    )
    return _ratio(hits, len(drafted))


def _mean(values: list[float], digits: int) -> float | None:
    return round(float(np.mean(values)), digits) if values else None


def _p95(values: list[float]) -> float | None:
    return round(float(np.percentile(values, 95)), 3) if values else None


def _draft_counts(outcomes: Sequence[CaseOutcome]) -> dict[str, int]:
    delivered = sum(1 for o in outcomes if o.run.delivered)
    parsed = sum(1 for o in outcomes if o.run.case_file is not None)
    return {
        "cases": len(outcomes),
        "drafts_parsed": parsed,
        "drafts_delivered": delivered,
        "drafts_rejected_by_checker": parsed - delivered,
    }


def _usage(outcomes: Sequence[CaseOutcome]) -> dict[str, Any]:
    usages = [o.run.usage for o in outcomes]
    return {
        "cost_per_case_usd_mean": _mean([u.cost_usd for u in usages], 6),
        "latency_seconds_p95": _p95([u.latency_ms / 1000 for u in usages]),
        "tokens_per_case_mean": _mean([float(u.total_tokens) for u in usages], 1),
    }


def summarise(outcomes: Sequence[CaseOutcome]) -> dict[str, Any]:
    """Every copilot metric for one provider."""
    counts = _claim_counts(outcomes)
    drafted = [(o, o.run.case_file) for o in outcomes if o.run.case_file is not None]
    return {
        **_draft_counts(outcomes),
        "unsupported_claim_rate_before_checker": _ratio(counts["unsupported"], counts["claims"]),
        "unsupported_claims_reaching_analyst": counts["delivered_unsupported"],
        "citation_coverage": _ratio(counts["cited"], counts["claims"]),
        "relevant_transaction_recall": _relevant_recall(outcomes),
        "typology_accuracy": _typology_accuracy(drafted),
        "action_agreement": _action_agreement(drafted),
        "completeness": _ratio(sum(1 for o in outcomes if _complete(o)), len(outcomes)),
        **_usage(outcomes),
        "errors": sorted({o.run.error for o in outcomes if o.run.error}),
    }
