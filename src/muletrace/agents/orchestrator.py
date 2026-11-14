"""The copilot: three small agents coordinated by plain Python, plus the single-call baseline.

1. The **evidence agent** calls tools (transfers, risk profile, policy lookup) and writes
   findings that cite transaction IDs.
2. The **typology agent** labels the laundering pattern from the findings.
3. The **report agent** turns findings and typology into a structured case file.

Every draft then goes through the deterministic fact checker; a draft that fails never reaches
the analyst. Each case has a token budget: if a case exceeds it, the run stops and the case
counts as failed, so cost per case is bounded by construction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

from pydantic import ValidationError

from muletrace.agents.case import CaseEvidence, CaseFile
from muletrace.agents.llm import ModelClient, ModelPrice, Usage
from muletrace.agents.tools import TOOL_SPECS, ToolBox
from muletrace.validation.fact_checker import CheckResult, check_case_file

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class TokenBudgetExceededError(RuntimeError):
    """Raised when a case uses more tokens than its budget allows."""


@cache
def prompt(name: str) -> str:
    """System prompt shipped with the package."""
    return resources.files("muletrace.agents.prompts").joinpath(f"{name}.md").read_text("utf-8")


def parse_json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in a model answer, or ``None``."""
    match = _JSON_OBJECT.search(text)
    if match is None:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


@dataclass
class CopilotRun:
    """Outcome of drafting one case."""

    case_file: CaseFile | None
    check: CheckResult | None
    usage: Usage
    tool_calls: int = 0
    error: str | None = None
    steps: list[str] = field(default_factory=list)

    @property
    def delivered(self) -> bool:
        """A draft reaches the analyst only if it parsed and passed the checker."""
        return self.case_file is not None and self.check is not None and self.check.passed


@dataclass
class _Session:
    client: ModelClient
    price: ModelPrice | None
    budget_tokens: int
    usage: Usage

    def ask(
        self, system: str, messages: list[dict[str, Any]], tools: tuple[dict[str, Any], ...] = ()
    ) -> Any:  # noqa: ANN401
        reply = self.client.converse(system, messages, tools)
        self.usage.add(reply, self.price)
        if self.usage.total_tokens > self.budget_tokens:
            raise TokenBudgetExceededError(f"{self.usage.total_tokens} tokens")
        return reply


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"text": text}]}


def _evidence_agent(session: _Session, evidence: CaseEvidence, max_rounds: int) -> tuple[str, int]:
    tools = ToolBox(evidence)
    messages = [_user(f"Investigate case {evidence.case_id}, account {evidence.account_id}.")]
    for _ in range(max_rounds):
        reply = session.ask(prompt("evidence"), messages, TOOL_SPECS)
        if not reply.tool_calls:
            return reply.text, tools.calls
        messages.append({"role": "assistant", "content": reply.raw_message.get("content", [])})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": call["toolUseId"],
                            "content": [{"text": tools.run(call["name"], call.get("input", {}))}],
                        }
                    }
                    for call in reply.tool_calls
                ],
            }
        )
    reply = session.ask(prompt("evidence"), [*messages, _user("Write your findings now.")])
    return reply.text, tools.calls


def _finish(evidence: CaseEvidence, answer: str, run: CopilotRun) -> CopilotRun:
    payload = parse_json_object(answer)
    if payload is None:
        run.error = "no JSON object in the answer"
        return run
    try:
        run.case_file = CaseFile.model_validate(payload)
    except ValidationError as error:
        run.error = f"invalid case file: {error.error_count()} field errors"
        return run
    run.check = check_case_file(run.case_file, evidence)
    return run


def run_multi_agent(
    evidence: CaseEvidence,
    client: ModelClient,
    price: ModelPrice | None,
    budget_tokens: int,
    max_tool_rounds: int = 4,
) -> CopilotRun:
    """Evidence agent, then typology agent, then report agent, then the fact checker."""
    run = CopilotRun(case_file=None, check=None, usage=Usage())
    session = _Session(client, price, budget_tokens, run.usage)
    try:
        findings, run.tool_calls = _evidence_agent(session, evidence, max_tool_rounds)
        run.steps.append("evidence")
        typology = session.ask(prompt("typology"), [_user(findings)]).text
        run.steps.append("typology")
        request = (
            f"case_id: {evidence.case_id}\naccount_id: {evidence.account_id}\n\n"
            f"Findings:\n{findings}\n\nTypology:\n{typology}"
        )
        answer = session.ask(prompt("report"), [_user(request)]).text
        run.steps.append("report")
    except TokenBudgetExceededError as error:
        run.error = f"token budget exceeded: {error}"
        return run
    return _finish(evidence, answer, run)


def run_single_call(
    evidence: CaseEvidence, client: ModelClient, price: ModelPrice | None, budget_tokens: int
) -> CopilotRun:
    """Baseline: one call with all the evidence in the prompt, then the fact checker."""
    run = CopilotRun(case_file=None, check=None, usage=Usage())
    session = _Session(client, price, budget_tokens, run.usage)
    try:
        answer = session.ask(prompt("single_call"), [_user(evidence.prompt_view())]).text
    except TokenBudgetExceededError as error:
        run.error = f"token budget exceeded: {error}"
        return run
    run.steps.append("single_call")
    return _finish(evidence, answer, run)
