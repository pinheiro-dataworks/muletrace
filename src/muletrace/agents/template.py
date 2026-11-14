"""Deterministic template baseline: a case file written by rules, with no model at all.

The multi-agent copilot has to beat this. It reads only the structure of the evidence (who sent
money to the account, whom the account paid, in which order), never the transfer descriptions,
so it cannot be steered by text planted in them.

Typology heuristic, on the account's ACH transfers in the window (the format that carries most
laundering in AMLworld, see the EDA): many senders and few receivers is fan-in, the opposite is
fan-out; several of both is gather-scatter when inflows come first and scatter-gather otherwise;
exactly one of each is a stack (a hop in a chain); anything else is labelled random. Accounts
with too little ACH activity get ``NONE`` and the action ``close``.
"""

from __future__ import annotations

from typing import Final

from muletrace.agents.case import CaseEvidence, CaseFile, Claim, EvidenceTransfer

MANY: Final = 3
_FAN_POLICY: Final = ["br-med-2", "muletrace-human-approval"]


def _parties(transfers: list[EvidenceTransfer], direction: str) -> set[int]:
    return {t.counterparty_id for t in transfers if t.direction == direction}


def _mixed_shape(transfers: list[EvidenceTransfer]) -> str:
    """Several senders and several receivers: which side moved first."""
    first_in = min(t.timestamp for t in transfers if t.direction == "in")
    first_out = min(t.timestamp for t in transfers if t.direction == "out")
    return "GATHER-SCATTER" if first_in <= first_out else "SCATTER-GATHER"


def classify_typology(transfers: list[EvidenceTransfer]) -> str:
    """Rule-based typology from the shape of the account's ACH flows."""
    senders = len(_parties(transfers, "in"))
    receivers = len(_parties(transfers, "out"))
    shapes = [
        (senders == receivers == 0, "NONE"),
        (senders >= MANY and receivers <= 1, "FAN-IN"),
        (receivers >= MANY and senders <= 1, "FAN-OUT"),
        (min(senders, receivers) >= 2, "MIXED"),  # noqa: PLR2004 - "several of both"
        (senders == receivers == 1, "STACK"),
    ]
    shape = next((name for matched, name in shapes if matched), "RANDOM")
    return _mixed_shape(transfers) if shape == "MIXED" else shape


def _claim(transfer: EvidenceTransfer, account_id: int) -> Claim:
    verb = "received" if transfer.direction == "in" else "sent"
    preposition = "from" if transfer.direction == "in" else "to"
    return Claim(
        text=(
            f"On {transfer.timestamp:%Y-%m-%d} account {account_id} {verb} "
            f"{transfer.amount_usd:,.2f} USD by {transfer.payment_format} {preposition} account "
            f"{transfer.counterparty_id} (tx {transfer.tx_id})."
        ),
        tx_ids=[transfer.tx_id],
        amounts_usd=[transfer.amount_usd],
        dates=[transfer.timestamp.date().isoformat()],
        account_ids=[account_id, transfer.counterparty_id],
    )


def template_case_file(evidence: CaseEvidence, max_claims: int = 6) -> CaseFile:
    """Draft a case file from the evidence structure alone."""
    ach = [t for t in evidence.transfers if t.payment_format == "ACH"]
    typology = classify_typology(ach)
    action = "close" if typology == "NONE" else "hold"
    largest = sorted(ach or list(evidence.transfers), key=lambda t: -t.amount_usd)[:max_claims]
    claims = [_claim(t, evidence.account_id) for t in sorted(largest, key=lambda t: t.timestamp)]
    senders, receivers = _parties(ach, "in"), _parties(ach, "out")
    summary = (
        f"Account {evidence.account_id} has {len(ach)} ACH transfers in the window, from "
        f"{len(senders)} distinct senders and to {len(receivers)} distinct receivers. "
        f"The flow shape matches {typology.lower()}; recommended action: {action}, pending "
        "analyst review."
    )
    return CaseFile(
        case_id=evidence.case_id,
        account_id=evidence.account_id,
        summary=summary,
        claims=claims,
        typology=typology,
        recommended_action=action,
        policy_refs=_FAN_POLICY if action == "hold" else ["muletrace-human-approval"],
    )
