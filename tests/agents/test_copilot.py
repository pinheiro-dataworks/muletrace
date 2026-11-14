from datetime import datetime

import polars as pl
import pytest

from muletrace.agents.case import CaseEvidence, build_evidence
from muletrace.agents.template import classify_typology, template_case_file
from muletrace.policy.loader import load_policies, lookup, policy_ids
from tests.agents.conftest import transfer
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
