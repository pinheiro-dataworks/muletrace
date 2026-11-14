from datetime import datetime

import polars as pl

from muletrace.agents.case import build_evidence
from muletrace.policy.loader import load_policies, lookup, policy_ids
from tests.fixtures.frames import transactions_frame


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
