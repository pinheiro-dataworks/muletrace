"""Parse AMLworld ``*_Patterns.txt`` files and link each pattern row to its ``tx_id``.

A patterns file lists laundering attempts that follow one of eight typologies::

    BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 16-degree Fan-Out
    2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH,1
    ...
    END LAUNDERING ATTEMPT - FAN-OUT

Each row repeats a line of the transactions CSV. Rows are matched back to ``tx_id`` on every
field. The source contains a few byte-identical transactions, so matching also uses the rank
of a row among its identical copies; this keeps the match one-to-one.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from muletrace.data.amlworld_loader import RAW_TRANSACTION_SCHEMA

TYPOLOGIES: Final = (
    "BIPARTITE",
    "CYCLE",
    "FAN-IN",
    "FAN-OUT",
    "GATHER-SCATTER",
    "RANDOM",
    "SCATTER-GATHER",
    "STACK",
)
TypologyDtype: Final = pl.Enum(TYPOLOGIES)

_BEGIN = re.compile(r"^BEGIN LAUNDERING ATTEMPT - (?P<typology>[A-Z-]+)(?::\s*(?P<detail>.*))?$")
_END = re.compile(r"^END LAUNDERING ATTEMPT - (?P<typology>[A-Z-]+)$")
_RAW_FIELDS: Final = tuple(RAW_TRANSACTION_SCHEMA.names())


class PatternFormatError(ValueError):
    """Raised when a patterns file is not well formed."""


@dataclass(frozen=True)
class LaunderingAttempt:
    """One ``BEGIN … END`` block of a patterns file."""

    attempt_id: int
    typology: str
    detail: str
    rows: tuple[str, ...]


class _AttemptParser:
    """Line-by-line state machine behind :func:`parse_patterns`."""

    def __init__(self) -> None:
        self.attempts: list[LaunderingAttempt] = []
        self._open: tuple[str, str] | None = None
        self._rows: list[str] = []

    def feed(self, line_number: int, line: str) -> None:
        if begin := _BEGIN.match(line):
            self._begin(line_number, begin["typology"], (begin["detail"] or "").strip())
        elif end := _END.match(line):
            self._end(line_number, end["typology"])
        elif self._open is None:
            raise PatternFormatError(f"line {line_number}: transaction row outside an attempt")
        else:
            self._rows.append(line)

    def _begin(self, line_number: int, typology: str, detail: str) -> None:
        if self._open is not None:
            raise PatternFormatError(f"line {line_number}: BEGIN inside an open attempt")
        if typology not in TYPOLOGIES:
            raise PatternFormatError(f"line {line_number}: unknown typology {typology!r}")
        self._open, self._rows = (typology, detail), []

    def _end(self, line_number: int, typology: str) -> None:
        if self._open is None or typology != self._open[0]:
            raise PatternFormatError(f"line {line_number}: END does not close the open attempt")
        attempt_id = len(self.attempts)
        self.attempts.append(
            LaunderingAttempt(attempt_id, self._open[0], self._open[1], tuple(self._rows))
        )
        self._open = None

    def finish(self) -> list[LaunderingAttempt]:
        if self._open is not None:
            raise PatternFormatError("file ends inside an open attempt")
        return self.attempts


def parse_patterns(text: str) -> list[LaunderingAttempt]:
    """Split a patterns file into attempts, validating that every block is closed.

    Raises:
        PatternFormatError: on a row outside a block, a nested block, a mismatched ``END`` or an
            unknown typology.
    """
    parser = _AttemptParser()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if line := raw_line.strip():
            parser.feed(line_number, line)
    return parser.finish()


def attempts_table(attempts: list[LaunderingAttempt]) -> pl.DataFrame:
    """One row per attempt: ``attempt_id``, ``typology``, ``detail``, ``n_rows``."""
    return pl.DataFrame(
        {
            "attempt_id": [a.attempt_id for a in attempts],
            "typology": [a.typology for a in attempts],
            "detail": [a.detail for a in attempts],
            "n_rows": [len(a.rows) for a in attempts],
        },
        schema={
            "attempt_id": pl.UInt32,
            "typology": TypologyDtype,
            "detail": pl.String,
            "n_rows": pl.UInt32,
        },
    )


def _pattern_rows(attempts: list[LaunderingAttempt]) -> pl.DataFrame:
    csv_text = "\n".join(row for attempt in attempts for row in attempt.rows)
    attempt_ids = [attempt.attempt_id for attempt in attempts for _ in attempt.rows]
    if not csv_text:
        return pl.DataFrame(schema={"attempt_id": pl.UInt32, **RAW_TRANSACTION_SCHEMA})
    rows = pl.read_csv(io.StringIO(csv_text), has_header=False, schema=RAW_TRANSACTION_SCHEMA)
    return rows.with_columns(attempt_id=pl.Series(attempt_ids, dtype=pl.UInt32))


def link_pattern_transactions(
    attempts: list[LaunderingAttempt], raw_transactions: pl.LazyFrame
) -> pl.DataFrame:
    """Map every pattern row to the ``tx_id`` of the identical transactions-file row.

    Returns ``attempt_id``, ``typology`` and ``tx_id``; ``tx_id`` is null for a row that has no
    counterpart in the transactions file, so callers can count and report unmatched rows.
    """
    copy_rank = pl.int_range(pl.len()).over(_RAW_FIELDS).alias("copy_rank")
    pattern_rows = _pattern_rows(attempts).with_columns(copy_rank)
    candidates = (
        raw_transactions.filter(pl.col("is_laundering") == 1)
        .sort("tx_id")
        .with_columns(copy_rank)
        .select(*_RAW_FIELDS, "copy_rank", "tx_id")
        .collect()
    )
    typologies = attempts_table(attempts).select("attempt_id", "typology")
    return (
        pattern_rows.join(candidates, on=[*_RAW_FIELDS, "copy_rank"], how="left", nulls_equal=True)
        .join(typologies, on="attempt_id")
        .select("attempt_id", "typology", "tx_id")
        .sort("attempt_id", "tx_id")
    )


def read_patterns(path: Path) -> list[LaunderingAttempt]:
    """Read and parse a patterns file from disk."""
    return parse_patterns(path.read_text(encoding="utf-8"))
