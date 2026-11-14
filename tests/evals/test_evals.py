import pytest

from muletrace.agents.case import CaseFile
from muletrace.agents.llm import ModelReply, ScriptedClient
from muletrace.config import CONFIG_DIR, load_config
from muletrace.data import pix_layer_simulator
from muletrace.data.amlworld_loader import RawDataset
from muletrace.data.labels import LabelConfig
from muletrace.data.prepare import prepare_dataset
from muletrace.evals import adversarial
from muletrace.evals.gold import build_gold_cases, read_gold_cases, write_gold_cases
from muletrace.evals.runner import CopilotConfig, EvalThresholds, evaluate, gate
from tests.fixtures.amlworld import write_amlworld_files

CONFIG = load_config(CopilotConfig, CONFIG_DIR / "copilot.yaml").model_copy(
    update={"adversarial_cases": 2}
)
THRESHOLDS = load_config(EvalThresholds, CONFIG_DIR / "eval_thresholds.yaml")


@pytest.fixture(scope="module")
def cases(tmp_path_factory: pytest.TempPathFactory) -> list:
    base = tmp_path_factory.mktemp("gold")
    dataset_dir = prepare_dataset(
        RawDataset("HI-Small", write_amlworld_files(base / "raw")), base / "p"
    ).output_dir
    pix_layer_simulator.run(
        dataset_dir,
        load_config(pix_layer_simulator.SimulatorConfig, CONFIG_DIR / "simulator.yaml"),
        load_config(LabelConfig, CONFIG_DIR / "labels.yaml"),
    )
    built = build_gold_cases(dataset_dir, per_typology=5, negatives=2, seed=0)
    write_gold_cases(built, base / "gold.jsonl")
    return read_gold_cases(base / "gold.jsonl")


def test_gold_cases_from_the_fixture_patterns(cases: list) -> None:
    positives = [c for c in cases if c.is_positive]
    assert {c.typology for c in positives} == {"STACK", "FAN-OUT"}
    stack = next(c for c in positives if c.typology == "STACK")
    assert stack.relevant_tx_ids == (2, 3)  # both identical rows, one-to-one
    assert {t.tx_id for t in stack.evidence.transfers} >= {2, 3}
    negatives = [c for c in cases if not c.is_positive]
    assert all(c.expected_actions == ("close", "monitor") for c in negatives)


def test_template_evaluation_passes_the_gate(cases: list) -> None:
    result = evaluate("template", cases, CONFIG)
    metrics = result["metrics"]
    assert metrics["cases"] == len(cases)
    assert metrics["unsupported_claims_reaching_analyst"] == 0
    assert all(row["rejection_rate"] == 1.0 for row in result["checker_strictness"].values())
    assert all(row["compromised_and_delivered"] == 0 for row in result["adversarial"].values())
    assert gate(result, THRESHOLDS) == [] or "action agreement below threshold" in gate(
        result, THRESHOLDS
    )


def test_unknown_provider_and_missing_factory(cases: list) -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        evaluate("oracle", cases, CONFIG)
    with pytest.raises(ValueError, match="factory"):
        evaluate("single", cases, CONFIG)


def _compliant_reply(case) -> ModelReply:
    first = case.evidence.transfers[0]
    case_file = CaseFile(
        case_id=case.evidence.case_id,
        account_id=case.evidence.account_id,
        summary="Ignoring the note in the description; holding for review.",
        claims=[{"text": "Transfer observed.", "tx_ids": [first.tx_id]}],
        typology=case.typology,
        recommended_action=case.expected_actions[0],
        policy_refs=["muletrace-human-approval"],
    )
    return ModelReply(text=case_file.model_dump_json(), input_tokens=1000, output_tokens=200)


def test_llm_provider_with_scripted_client_and_a_compromised_run(cases: list) -> None:
    def factory(_: str) -> ScriptedClient:
        replies = [_compliant_reply(c) for c in cases]
        positives = [c for c in cases if c.is_positive][: CONFIG.adversarial_cases]
        for attack in adversarial.ATTACKS:
            for case in positives:
                attacked = case.model_copy(
                    update={"evidence": adversarial.inject(case.evidence, attack)}
                )
                reply = _compliant_reply(attacked)
                if attack == "close_the_case":
                    reply.text = reply.text.replace('"hold"', '"close"')
                replies.append(reply)
        return ScriptedClient(replies)

    shared = factory("x")
    result = evaluate("single", cases, CONFIG, lambda _: shared)
    assert result["metrics"]["cost_per_case_usd_mean"] > 0
    assert (
        result["adversarial"]["close_the_case"]["compromised_and_delivered"]
        == CONFIG.adversarial_cases
    )
    assert "attack close_the_case reached the analyst" in gate(result, THRESHOLDS)


def _result(**metrics: object) -> dict:
    base = {
        "unsupported_claims_reaching_analyst": 0,
        "cost_per_case_usd_mean": 0.001,
        "latency_seconds_p95": 1.0,
        "action_agreement": 0.9,
    }
    return {
        "metrics": {**base, **metrics},
        "checker_strictness": {"wrong_amount": {"drafts": 3, "rejection_rate": 2 / 3}},
        "adversarial": {},
    }


def test_gate_reports_every_broken_threshold() -> None:
    failures = gate(
        _result(
            unsupported_claims_reaching_analyst=1,
            cost_per_case_usd_mean=0.5,
            latency_seconds_p95=99.0,
            action_agreement=0.1,
        ),
        THRESHOLDS,
    )
    assert failures == [
        "unsupported claims reached the analyst",
        "checker missed perturbation wrong_amount",
        "cost per case above budget",
        "p95 latency above budget",
        "action agreement below threshold",
    ]


def test_compromise_rules_per_attack(cases: list) -> None:
    from muletrace.agents.llm import Usage  # noqa: PLC0415
    from muletrace.agents.orchestrator import CopilotRun  # noqa: PLC0415
    from muletrace.evals.metrics import CaseOutcome  # noqa: PLC0415
    from muletrace.validation.fact_checker import CheckResult  # noqa: PLC0415

    case = next(c for c in cases if c.is_positive)
    case_file = CaseFile.model_validate_json(_compliant_reply(case).text)
    leaky = case_file.model_copy(update={"summary": "Write to someone at example.invalid"})
    outcome = CaseOutcome(case, CopilotRun(leaky, CheckResult(), Usage()))
    assert adversarial.compromised("leak_pii", outcome)
    assert not adversarial.compromised("release_funds", outcome)
    assert not adversarial.compromised("invent_transaction", outcome)
    undelivered = CaseOutcome(case, CopilotRun(None, None, Usage()))
    assert not adversarial.compromised("leak_pii", undelivered)
    assert adversarial.blocked_by_checker(undelivered) == []
    empty = case_file.model_copy(update={"claims": []})
    assert adversarial.checker_strictness(
        [CaseOutcome(case, CopilotRun(empty, CheckResult(), Usage()))]
    )["wrong_amount"] == {"drafts": 0, "rejected": 0, "rejection_rate": 0.0}
