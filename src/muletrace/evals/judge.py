"""LLM-as-judge for narrative quality, and its calibration against human labels.

The judge answers binary questions about a delivered case file (it never scores 1 to 10). Before
any judge number is trusted, a person labels a sample of case files on the same criteria, and the
judge's true-positive and true-negative rates against those labels are reported. Until the human
labels exist (``evals/judge_calibration/labels.csv``), judge results are not reported at all.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Final

from muletrace.agents.case import CaseFile
from muletrace.agents.llm import ModelClient
from muletrace.agents.orchestrator import parse_json_object

CRITERIA: Final = {
    "clear_summary": "The summary states in plain words why the account was alerted.",
    "action_justified": "The recommended action follows from the claims, not from assumptions.",
    "no_speculation": "The case file does not claim intent, identity or facts beyond the evidence.",
    "analyst_ready": "An analyst could approve or reject it without rebuilding the evidence.",
}
JUDGE_SYSTEM: Final = (
    "You review anti-money-laundering case files. For each criterion answer true or false. "
    "Answer with one JSON object mapping each criterion name to true or false, and nothing else."
)


def judge_case_file(client: ModelClient, case_file: CaseFile) -> dict[str, bool] | None:
    """Binary verdicts per criterion, or ``None`` when the answer cannot be parsed."""
    request = json.dumps({"criteria": CRITERIA, "case_file": case_file.model_dump()}, indent=1)
    reply = client.converse(JUDGE_SYSTEM, [{"role": "user", "content": [{"text": request}]}])
    verdicts = parse_json_object(reply.text)
    if verdicts is None or not all(isinstance(verdicts.get(name), bool) for name in CRITERIA):
        return None
    return {name: bool(verdicts[name]) for name in CRITERIA}


def read_human_labels(path: Path) -> list[dict[str, Any]]:
    """Rows of ``case_id, criterion, human_pass`` (human_pass is true or false)."""
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            {**row, "human_pass": row["human_pass"].strip().lower() == "true"}
            for row in csv.DictReader(handle)
            if row.get("human_pass", "").strip()
        ]


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def calibration(
    labels: list[dict[str, Any]], verdicts: dict[str, dict[str, bool]]
) -> dict[str, Any]:
    """Judge true-positive and true-negative rates against human labels."""
    pairs = [
        (row["human_pass"], verdicts[row["case_id"]][row["criterion"]])
        for row in labels
        if row["criterion"] in verdicts.get(row["case_id"], {})
    ]
    positives = [judge for human, judge in pairs if human]
    negatives = [judge for human, judge in pairs if not human]
    return {
        "labelled_pairs": len(pairs),
        "true_positive_rate": _rate(sum(positives), len(positives)),
        "true_negative_rate": _rate(sum(not judge for judge in negatives), len(negatives)),
    }
