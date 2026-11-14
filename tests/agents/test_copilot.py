import json
from datetime import datetime

import polars as pl
import pytest

from muletrace.agents.case import CaseEvidence, CaseFile, build_evidence
from muletrace.agents.llm import BedrockClient, ModelPrice, ModelReply, ScriptedClient, Usage
from muletrace.agents.orchestrator import (
    parse_json_object,
    prompt,
    run_multi_agent,
    run_single_call,
)
from muletrace.agents.template import classify_typology, template_case_file
from muletrace.agents.tools import TOOL_SPECS, ToolBox
from muletrace.policy.loader import load_policies, lookup, policy_ids
from tests.agents.conftest import transfer
from tests.fixtures.frames import transactions_frame

PRICE = ModelPrice(input_per_1k=0.00006, output_per_1k=0.00024)


def test_policy_library_entries_have_sources() -> None:
    entries = load_policies()
    assert len(entries) >= 8
    assert all(entry.source and entry.summary for entry in entries)
    assert "br-med-2" in policy_ids()
    assert lookup("dispute return med")[0].id.startswith("br-med")
    assert lookup("nothing matches zzz") == []


def test_build_evidence_keeps_required_transfers_and_time_order() -> None:
    frame = transactions_frame(
        [
            (0, 1, 2, 5.0, False),
            (10, 3, 2, 900.0, False),
            (20, 2, 4, 50.0, True),
            (30, 2, 2, 1.0, False),
        ]
    )
    frame = frame.with_columns(payment_format=pl.lit("ACH"))
    descriptions = pl.DataFrame(
        {"tx_id": [2], "description": ["Groceries"]},
        schema={"tx_id": pl.UInt32, "description": pl.String},
    )
    evidence = build_evidence(
        case_id="c",
        dataset="HI-Small",
        account_id=2,
        transactions=frame,
        descriptions=descriptions,
        window=(datetime(2022, 9, 1), datetime(2022, 9, 2)),
        max_transfers=1,
        must_include=frozenset({0}),
    )
    assert [t.tx_id for t in evidence.transfers] == [0]  # required beats larger
    wider = build_evidence(
        case_id="c",
        dataset="HI-Small",
        account_id=2,
        transactions=frame,
        descriptions=descriptions,
        window=(datetime(2022, 9, 1), datetime(2022, 9, 2)),
        max_transfers=5,
    )
    assert [(t.tx_id, t.direction) for t in wider.transfers] == [(0, "in"), (1, "in"), (2, "out")]
    assert wider.transfer(2).description == "Groceries"
    assert wider.transfer(3) is None
    assert "tx_id | time" in wider.prompt_view()


@pytest.mark.parametrize(
    ("shape", "expected"),
    [
        ([("in", 1), ("in", 2), ("in", 3), ("out", 9)], "FAN-IN"),
        ([("in", 1), ("out", 7), ("out", 8), ("out", 9)], "FAN-OUT"),
        ([("in", 1), ("in", 2), ("out", 8), ("out", 9)], "GATHER-SCATTER"),
        ([("out", 8), ("out", 9), ("in", 1), ("in", 2)], "SCATTER-GATHER"),
        ([("in", 1), ("out", 9)], "STACK"),
        ([("in", 1), ("in", 2)], "RANDOM"),
        ([], "NONE"),
    ],
)
def test_template_typology_rules(shape: list[tuple[str, int]], expected: str) -> None:
    transfers = [transfer(i, 10 + i, d, c, 10.0) for i, (d, c) in enumerate(shape)]
    assert classify_typology(transfers) == expected


def test_template_case_file_passes_the_checker(evidence: CaseEvidence) -> None:
    from muletrace.validation.fact_checker import check_case_file  # noqa: PLC0415

    case_file = template_case_file(evidence)
    assert case_file.typology == "FAN-IN"
    assert case_file.recommended_action == "hold"
    assert check_case_file(case_file, evidence).passed
    quiet = evidence.model_copy(
        update={"transfers": (transfer(9, 10, "in", 1, 1.0, fmt="Cheque"),)}
    )
    assert template_case_file(quiet).recommended_action == "close"


def test_toolbox_caches_and_separates_customer_text(evidence: CaseEvidence) -> None:
    tools = ToolBox(evidence)
    first = json.loads(tools.run("get_transfers", {"direction": "in", "limit": 2}))
    tools.run("get_transfers", {"direction": "in", "limit": 2})
    assert tools.calls == 1
    assert [t["tx_id"] for t in first["transfers"]] == [3, 2]
    assert first["untrusted_customer_text"] == {}
    assert json.loads(tools.run("get_risk_profile", {}))["risk_probability"] == 0.4
    assert json.loads(tools.run("lookup_policy", {"query": "return"}))["policies"]
    assert "error" in json.loads(tools.run("delete_everything", {}))
    assert {spec["name"] for spec in TOOL_SPECS} == {
        "get_transfers",
        "get_risk_profile",
        "lookup_policy",
    }


def test_bedrock_client_builds_the_converse_request() -> None:
    class Runtime:
        def __init__(self) -> None:
            self.request: dict = {}

        def converse(self, **request: object) -> dict:
            self.request = request
            return {
                "output": {
                    "message": {
                        "content": [
                            {"text": "hi"},
                            {"toolUse": {"toolUseId": "1", "name": "x", "input": {}}},
                        ]
                    }
                },
                "usage": {"inputTokens": 1000, "outputTokens": 500},
                "stopReason": "guardrail_intervened",
            }

    runtime = Runtime()
    client = BedrockClient("amazon.nova-lite-v1:0", runtime, guardrail_id="g-1")
    reply = client.converse("system", [{"role": "user", "content": [{"text": "q"}]}], TOOL_SPECS)
    assert runtime.request["inferenceConfig"]["temperature"] == 0.0
    assert runtime.request["guardrailConfig"]["guardrailIdentifier"] == "g-1"
    assert len(runtime.request["toolConfig"]["tools"]) == len(TOOL_SPECS)
    assert (reply.text, len(reply.tool_calls), reply.guardrail_intervened) == ("hi", 1, True)
    usage = Usage()
    usage.add(reply, PRICE)
    assert usage.cost_usd == pytest.approx(1000 * 0.00006 / 1000 + 500 * 0.00024 / 1000)


def _reply(text: str = "", tool_calls: list | None = None, tokens: int = 100) -> ModelReply:
    content = [{"toolUse": call} for call in tool_calls or []]
    return ModelReply(
        text=text,
        tool_calls=tool_calls or [],
        input_tokens=tokens,
        output_tokens=tokens,
        raw_message={"role": "assistant", "content": content},
    )


def test_multi_agent_run_with_tools(evidence: CaseEvidence, good_file: CaseFile) -> None:
    client = ScriptedClient(
        [
            _reply(
                tool_calls=[
                    {"toolUseId": "a", "name": "get_transfers", "input": {"direction": "both"}}
                ]
            ),
            _reply("Findings: tx 1, 2, 3 in; tx 4 out."),
            _reply('{"typology": "FAN-IN", "rationale": "tx 1-3"}'),
            _reply("Here is the file:\n" + good_file.model_dump_json()),
        ]
    )
    run = run_multi_agent(evidence, client, PRICE, budget_tokens=10_000)
    assert run.delivered
    assert run.steps == ["evidence", "typology", "report"]
    assert run.tool_calls == 1
    assert run.usage.calls == 4
    assert "toolResult" in json.dumps(client.sent[1]["messages"])


def test_multi_agent_stops_at_the_tool_round_limit(
    evidence: CaseEvidence, good_file: CaseFile
) -> None:
    call = {"toolUseId": "a", "name": "get_risk_profile", "input": {}}
    client = ScriptedClient(
        [
            _reply(tool_calls=[call]),
            _reply("Findings."),
            _reply("{}"),
            _reply(good_file.model_dump_json()),
        ]
    )
    run = run_multi_agent(evidence, client, PRICE, budget_tokens=10_000, max_tool_rounds=1)
    assert run.delivered


def test_budget_and_parsing_failures(evidence: CaseEvidence) -> None:
    over = run_single_call(
        evidence, ScriptedClient([_reply("{}", tokens=10_000)]), PRICE, budget_tokens=100
    )
    assert over.error is not None
    assert "budget" in over.error
    assert not over.delivered
    multi = run_multi_agent(
        evidence, ScriptedClient([_reply("x", tokens=10_000)]), PRICE, budget_tokens=100
    )
    assert "budget" in (multi.error or "")
    no_json = run_single_call(
        evidence, ScriptedClient([_reply("I cannot help.")]), PRICE, budget_tokens=10_000
    )
    assert no_json.error == "no JSON object in the answer"
    invalid = run_single_call(
        evidence, ScriptedClient([_reply('{"case_id": 1}')]), PRICE, budget_tokens=10_000
    )
    assert (invalid.error or "").startswith("invalid case file")
    with pytest.raises(RuntimeError, match="no replies"):
        ScriptedClient([]).converse("s", [])


def test_parse_json_object_and_prompts() -> None:
    assert parse_json_object('text {"a": 1} more') == {"a": 1}
    assert parse_json_object("[1, 2]") is None
    assert parse_json_object("{broken") is None
    assert "untrusted_customer_text" in prompt("evidence")
    for name in ("typology", "report", "single_call"):
        assert "JSON" in prompt(name)
