"""Copilot Lambda: draft a case file for one alerted account.

The event is the case evidence (``CaseEvidence`` as JSON). The response always carries the
fact-checker result; a draft that fails it is returned with ``delivered: false`` and its
violations, so the analyst sees why there is nothing to approve. The copilot never acts: holding,
monitoring or closing is the analyst's decision.
"""

from __future__ import annotations

import json
import os
from typing import Any

from muletrace.agents.case import CaseEvidence
from muletrace.agents.llm import BedrockClient, ModelClient, ModelPrice
from muletrace.agents.orchestrator import run_multi_agent

DEFAULT_BUDGET_TOKENS = 20_000


def draft(
    event: dict[str, Any], client: ModelClient, price: ModelPrice | None, budget_tokens: int
) -> dict[str, Any]:
    """Run the copilot on one case and describe the outcome."""
    evidence = CaseEvidence.model_validate(event)
    run = run_multi_agent(evidence, client, price, budget_tokens)
    return {
        "case_id": evidence.case_id,
        "delivered": run.delivered,
        "case_file": run.case_file.model_dump() if run.delivered and run.case_file else None,
        "violations": [v.__dict__ for v in run.check.violations] if run.check else [],
        "error": run.error,
        "usage": {
            "input_tokens": run.usage.input_tokens,
            "output_tokens": run.usage.output_tokens,
            "cost_usd": round(run.usage.cost_usd, 6),
            "guardrail_interventions": run.usage.guardrail_interventions,
        },
    }


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:  # pragma: no cover
    """Lambda entry point; model, prices and guardrail come from the environment."""
    import boto3  # noqa: PLC0415

    client = BedrockClient(
        model_id=os.environ["AGENT_MODEL_ID"],
        runtime=boto3.client("bedrock-runtime"),
        guardrail_id=os.environ.get("BEDROCK_GUARDRAIL_ID"),
        guardrail_version=os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
    )
    price = ModelPrice.model_validate(json.loads(os.environ["AGENT_MODEL_PRICE"]))
    budget = int(os.environ.get("TOKEN_BUDGET_PER_CASE", DEFAULT_BUDGET_TOKENS))
    return draft(event, client, price, budget)
