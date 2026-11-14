"""Deterministic fact checker for drafted case files. No model is involved.

A draft is rejected if any of these fails:

* every claim cites at least one transaction, and every cited transaction is in the evidence;
* every amount in a claim equals a cited transfer's amount or the sum of the cited amounts
  (to the cent);
* every date in a claim is the date of a cited transfer;
* every account in a claim is the case account or a counterparty of a cited transfer;
* transaction IDs written in free text (``tx 123``, ``TX-123``) are cited and in the evidence;
* the typology and the recommended action are from the allowed lists, and the action is never
  to release or unblock funds;
* policy references exist in the policy library;
* no free text contains an e-mail address or a phone-number-like string (PII must not flow
  from transfer descriptions into a case file).

Every violation is reported, not only the first, so evaluation can count them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from muletrace.agents.case import (
    ACTIONS,
    TYPOLOGY_LABELS,
    CaseEvidence,
    CaseFile,
    Claim,
    EvidenceTransfer,
)
from muletrace.policy.loader import policy_ids

_CENT: Final = 0.01
_TX_IN_TEXT: Final = re.compile(r"\b(?:tx|transaction|transfer)[\s#:_-]*(\d{1,9})\b", re.IGNORECASE)
_EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Phone-like: digit groups joined by spaces or dashes, never by "." or "," (those are amounts).
_PHONE: Final = re.compile(
    r"(?<![\d.,])\+?(?:\d{1,3}[\s-])?\(?\d{2,3}\)?[\s-]\d{4,5}[\s-]?\d{4}(?!\d|[.,]\d)"
)
_RELEASE: Final = re.compile(
    r"\b(unblock|un-block|release|lift the hold|return the funds to)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Violation:
    """One reason a draft cannot reach the analyst."""

    rule: str
    detail: str
    claim_index: int | None = None


@dataclass
class CheckResult:
    """All violations of one draft."""

    violations: list[Violation] = field(default_factory=list)
    unsupported_claims: int = 0
    claims: int = 0

    @property
    def passed(self) -> bool:
        """True when the draft may be shown to an analyst."""
        return not self.violations


def _claim_violations(index: int, claim: Claim, evidence: CaseEvidence) -> list[Violation]:
    found: list[Violation] = []
    if not claim.tx_ids:
        found.append(Violation("uncited_claim", claim.text[:80], index))
    cited = []
    for tx_id in claim.tx_ids:
        transfer = evidence.transfer(tx_id)
        if transfer is None:
            found.append(Violation("unknown_transaction", str(tx_id), index))
        else:
            cited.append(transfer)
    if cited:
        found += _value_violations(index, claim, cited, evidence)
    for match in _TX_IN_TEXT.finditer(claim.text):
        if int(match.group(1)) not in claim.tx_ids:
            found.append(Violation("uncited_transaction_in_text", match.group(0), index))
    return found


def _wrong_amounts(claim: Claim, cited: list[EvidenceTransfer]) -> list[float]:
    """Amounts that match neither a cited transfer nor the sum of the cited transfers."""
    amounts = [t.amount_usd for t in cited]
    allowed = [*amounts, sum(amounts)]
    return [a for a in claim.amounts_usd if all(abs(a - v) > _CENT for v in allowed)]


def _value_violations(
    index: int, claim: Claim, cited: list[EvidenceTransfer], evidence: CaseEvidence
) -> list[Violation]:
    dates = {t.timestamp.date().isoformat() for t in cited}
    accounts = {evidence.account_id} | {t.counterparty_id for t in cited}
    wrong_dates = [d for d in claim.dates if d[:10] not in dates]
    wrong_accounts = [a for a in claim.account_ids if a not in accounts]
    return [
        *(Violation("amount_mismatch", f"{a:.2f}", index) for a in _wrong_amounts(claim, cited)),
        *(Violation("date_mismatch", d, index) for d in wrong_dates),
        *(Violation("account_mismatch", str(a), index) for a in wrong_accounts),
    ]


def _free_text(case_file: CaseFile) -> list[str]:
    return [case_file.summary, *(claim.text for claim in case_file.claims)]


_TEXT_RULES: Final = (
    ("release_recommended", _RELEASE),
    ("pii_email", _EMAIL),
    ("pii_phone", _PHONE),
)


def _header_violations(case_file: CaseFile, evidence: CaseEvidence) -> list[Violation]:
    """Case identity, typology, action and policy references."""
    known = policy_ids()
    checks = [
        (
            case_file.account_id != evidence.account_id or case_file.case_id != evidence.case_id,
            Violation("wrong_case", f"{case_file.case_id}/{case_file.account_id}"),
        ),
        (
            case_file.typology not in TYPOLOGY_LABELS,
            Violation("unknown_typology", case_file.typology),
        ),
        (
            case_file.recommended_action not in ACTIONS,
            Violation("unknown_action", case_file.recommended_action),
        ),
    ]
    return [violation for failed, violation in checks if failed] + [
        Violation("unknown_policy", ref) for ref in case_file.policy_refs if ref not in known
    ]


def _text_violations(case_file: CaseFile, evidence: CaseEvidence) -> list[Violation]:
    """Forbidden content anywhere in the text, and unknown transactions in the summary."""
    found = [
        Violation(rule, match.group(0))
        for text in _free_text(case_file)
        for rule, pattern in _TEXT_RULES
        for match in pattern.finditer(text)
    ]
    return found + [
        Violation("unknown_transaction_in_summary", match.group(0))
        for match in _TX_IN_TEXT.finditer(case_file.summary)
        if evidence.transfer(int(match.group(1))) is None
    ]


def check_case_file(case_file: CaseFile, evidence: CaseEvidence) -> CheckResult:
    """Verify a draft against the evidence it was written from."""
    result = CheckResult(claims=len(case_file.claims))
    for index, claim in enumerate(case_file.claims):
        claim_violations = _claim_violations(index, claim, evidence)
        if claim_violations:
            result.unsupported_claims += 1
        result.violations += claim_violations
    result.violations += _header_violations(case_file, evidence)
    result.violations += _text_violations(case_file, evidence)
    return result
