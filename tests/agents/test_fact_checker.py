import pytest

from muletrace.agents.case import CaseEvidence, CaseFile, Claim
from muletrace.validation.fact_checker import check_case_file


def _rules(case_file: CaseFile, evidence: CaseEvidence) -> set[str]:
    return {v.rule for v in check_case_file(case_file, evidence).violations}


def test_a_faithful_draft_passes(good_file: CaseFile, evidence: CaseEvidence) -> None:
    result = check_case_file(good_file, evidence)
    assert result.passed
    assert (result.claims, result.unsupported_claims) == (2, 0)


@pytest.mark.parametrize(
    ("claim", "rule"),
    [
        (Claim(text="No citation at all."), "uncited_claim"),
        (Claim(text="Invented.", tx_ids=[99]), "unknown_transaction"),
        (Claim(text="Wrong amount.", tx_ids=[1], amounts_usd=[101.0]), "amount_mismatch"),
        (Claim(text="Wrong date.", tx_ids=[1], dates=["2022-09-06"]), "date_mismatch"),
        (Claim(text="Wrong account.", tx_ids=[1], account_ids=[999]), "account_mismatch"),
        (Claim(text="See tx 3 for details.", tx_ids=[1]), "uncited_transaction_in_text"),
    ],
)
def test_each_claim_rule(
    claim: Claim, rule: str, good_file: CaseFile, evidence: CaseEvidence
) -> None:
    broken = good_file.model_copy(update={"claims": [*good_file.claims, claim]})
    result = check_case_file(broken, evidence)
    assert rule in {v.rule for v in result.violations}
    assert result.unsupported_claims == 1


def test_amounts_may_equal_the_sum_of_cited_transfers(
    good_file: CaseFile, evidence: CaseEvidence
) -> None:
    claim = Claim(text="Sum.", tx_ids=[1, 2], amounts_usd=[300.0, 100.0, 200.0])
    assert check_case_file(good_file.model_copy(update={"claims": [claim]}), evidence).passed


@pytest.mark.parametrize(
    ("update", "rule"),
    [
        ({"typology": "SMURFING"}, "unknown_typology"),
        ({"recommended_action": "freeze_forever"}, "unknown_action"),
        ({"policy_refs": ["made-up-policy"]}, "unknown_policy"),
        ({"summary": "Please release the funds."}, "release_recommended"),
        ({"summary": "Customer wrote from ana@example.invalid."}, "pii_email"),
        ({"summary": "Customer phone +55 11 98765-4321."}, "pii_phone"),
        ({"summary": "Linked to tx 424242."}, "unknown_transaction_in_summary"),
        ({"case_id": "other-case"}, "wrong_case"),
    ],
)
def test_file_level_rules(
    update: dict, rule: str, good_file: CaseFile, evidence: CaseEvidence
) -> None:
    assert rule in _rules(good_file.model_copy(update=update), evidence)


def test_amounts_are_not_mistaken_for_phone_numbers(
    good_file: CaseFile, evidence: CaseEvidence
) -> None:
    summary = "Inflows of 5,738,987.96 USD and 5738987.96 USD on 2022-09-05."
    assert "pii_phone" not in _rules(good_file.model_copy(update={"summary": summary}), evidence)
