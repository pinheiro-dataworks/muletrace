"""A small hand-made case: a fan-in into account 7, then one onward transfer."""

from datetime import datetime

import pytest

from muletrace.agents.case import CaseEvidence, CaseFile, Claim, EvidenceTransfer

T = datetime(2022, 9, 5, 10)


def transfer(  # noqa: PLR0917 - compact helper for hand-written cases
    tx_id: int, hour: int, direction: str, counterparty: int, amount: float, fmt: str = "ACH"
) -> EvidenceTransfer:
    return EvidenceTransfer(
        tx_id=tx_id,
        timestamp=T.replace(hour=hour),
        direction=direction,  # type: ignore[arg-type]
        counterparty_id=counterparty,
        amount_usd=amount,
        payment_format=fmt,
        description="Rent" if tx_id == 1 else "",
    )


@pytest.fixture
def evidence() -> CaseEvidence:
    return CaseEvidence(
        case_id="case-1",
        dataset="HI-Small",
        account_id=7,
        window_start=T.replace(hour=0),
        window_end=T.replace(hour=23),
        transfers=(
            transfer(1, 10, "in", 11, 100.0),
            transfer(2, 11, "in", 12, 200.0),
            transfer(3, 12, "in", 13, 300.0),
            transfer(4, 15, "out", 20, 550.0),
            transfer(5, 16, "in", 14, 5.0, fmt="Cheque"),
        ),
        risk_probability=0.4,
        reason_codes=("inflow_usd_24h",),
    )


@pytest.fixture
def good_file() -> CaseFile:
    return CaseFile(
        case_id="case-1",
        account_id=7,
        summary="Account 7 gathered money from three senders and forwarded most of it.",
        claims=[
            Claim(
                text="Three inflows (tx 1, tx 2, tx 3) totalled 600.00 USD on 2022-09-05.",
                tx_ids=[1, 2, 3],
                amounts_usd=[600.0],
                dates=["2022-09-05"],
                account_ids=[7, 11, 12, 13],
            ),
            Claim(
                text="It sent 550.00 USD to account 20.",
                tx_ids=[4],
                amounts_usd=[550.0],
                account_ids=[20],
            ),
        ],
        typology="FAN-IN",
        recommended_action="hold",
        policy_refs=["br-med-2"],
    )
