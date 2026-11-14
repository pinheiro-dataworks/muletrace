import pytest

from muletrace.data.patterns import PatternFormatError, attempts_table, parse_patterns

ROW = "2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH,1"


def test_parses_typology_detail_and_rows() -> None:
    text = (
        "BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 2-degree Fan-Out\n"
        f"{ROW}\n{ROW}\n"
        "END LAUNDERING ATTEMPT - FAN-OUT\n\n"
        "BEGIN LAUNDERING ATTEMPT - RANDOM\n"
        f"{ROW}\n"
        "END LAUNDERING ATTEMPT - RANDOM\n"
    )
    attempts = parse_patterns(text)
    assert [(a.attempt_id, a.typology, a.detail, len(a.rows)) for a in attempts] == [
        (0, "FAN-OUT", "Max 2-degree Fan-Out", 2),
        (1, "RANDOM", "", 1),
    ]
    table = attempts_table(attempts)
    assert table["n_rows"].to_list() == [2, 1]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (f"{ROW}\n", "outside an attempt"),
        ("BEGIN LAUNDERING ATTEMPT - CYCLE\nBEGIN LAUNDERING ATTEMPT - CYCLE\n", "BEGIN inside"),
        ("BEGIN LAUNDERING ATTEMPT - CYCLE\nEND LAUNDERING ATTEMPT - STACK\n", "does not close"),
        ("END LAUNDERING ATTEMPT - STACK\n", "does not close"),
        ("BEGIN LAUNDERING ATTEMPT - SMURFING\n", "unknown typology"),
        ("BEGIN LAUNDERING ATTEMPT - CYCLE\n", "ends inside"),
    ],
)
def test_malformed_files_are_rejected(text: str, message: str) -> None:
    with pytest.raises(PatternFormatError, match=message):
        parse_patterns(text)


def test_empty_file_has_no_attempts() -> None:
    assert parse_patterns("") == []
    assert attempts_table([]).height == 0
