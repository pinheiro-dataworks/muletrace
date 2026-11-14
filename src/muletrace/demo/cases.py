"""Precomputed cases for the static demo: what an analyst would see, end to end.

Each case is produced by the same code as the deployed system: the score and reason codes from
:class:`muletrace.serving.handler.ScoringService` (with an in-memory feature store), the evidence
from :func:`muletrace.agents.case.build_evidence`, a fund-flow trace when the account received
an accepted dispute, and a case file drafted by the model-free template and checked by the fact
checker. Nothing in a case is written by hand.

Two kinds of case are selected, both from AMLworld HI-Small (synthetic):

* accounts at evenly spaced ranks across the alert list of the last hold-out snapshot, whatever
  their label, so false positives are shown next to true ones;
* accounts that received an accepted MED-style dispute during the hold-out, scored on the
  snapshot before the disputed transfer.

The evidence window runs from three days before the score to one day after it: the analyst opens
the case the day after the alert and sees what happened since.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

import polars as pl

from muletrace.agents.case import CaseEvidence, build_evidence
from muletrace.agents.template import template_case_file
from muletrace.models.artifact import ModelArtifact
from muletrace.models.evaluate import alert_count
from muletrace.serving.batch import feature_items, score_snapshot
from muletrace.serving.feature_client import InMemoryFeatureStore
from muletrace.serving.handler import ScoringService
from muletrace.tracing.med_tracer import TracerConfig, trace
from muletrace.validation.fact_checker import check_case_file

LOOKBACK: Final = timedelta(days=3)
FOLLOW_UP: Final = timedelta(days=1)
MAX_TRANSFERS: Final = 25
PROBABILITY_CAP: Final = 0.99


def _ranked(snapshot: pl.DataFrame, artifact: ModelArtifact) -> pl.DataFrame:
    # Ranked by the raw score: calibrated probabilities tie at the top of the range.
    scores = score_snapshot(snapshot, artifact).select("account_id", "raw_score")
    return (
        snapshot.select("account_id", "label", "already_active")
        .join(scores, on="account_id")
        .sort(["raw_score", "account_id"], descending=[True, False])
        .with_row_index("rank", offset=1)
    )


def _trace_view(transactions: pl.LazyFrame, tx_id: int, config: TracerConfig) -> dict[str, Any]:
    result = trace(transactions, tx_id, config)
    if result.hops.height == 0:  # the money had not moved on: nothing to list
        return {**result.summary(), "hops": []}
    hops = result.hops.sort("hop").head(MAX_TRANSFERS)
    return {**result.summary(), "hops": hops.to_dicts()}


class DemoBuilder:
    """Builds demo cases for one dataset from its processed tables and cached snapshots."""

    def __init__(
        self,
        *,
        dataset: str,
        transactions: pl.LazyFrame,
        descriptions: pl.DataFrame,
        snapshots: pl.DataFrame,
        artifact: ModelArtifact,
        tracer: TracerConfig,
        budget_per_10k: float,
    ) -> None:
        self.dataset = dataset
        self.transactions = transactions
        self.descriptions = descriptions
        self.snapshots = snapshots
        self.artifact = artifact
        self.tracer = tracer
        self.budget = budget_per_10k
        store = InMemoryFeatureStore()
        store.put_many(feature_items(snapshots, artifact.features, dataset))
        self.service = ScoringService(artifact, store, dataset, PROBABILITY_CAP)

    def _snapshot(self, as_of: datetime) -> pl.DataFrame:
        return self.snapshots.filter(pl.col("as_of") == as_of)

    def case(
        self, case_id: str, account_id: int, as_of: datetime, disputed_tx_id: int | None
    ) -> dict[str, Any]:
        """One complete case."""
        ranked = _ranked(self._snapshot(as_of), self.artifact)
        row = ranked.filter(pl.col("account_id") == account_id).row(0, named=True)
        score = self.service.score(account_id, as_of.date().isoformat())
        if score is None:  # pragma: no cover - every selected account is in the snapshot
            raise KeyError(f"account {account_id} has no features at {as_of}")
        must_include = frozenset({disputed_tx_id} if disputed_tx_id is not None else set())
        evidence = build_evidence(
            case_id=case_id,
            dataset=self.dataset,
            account_id=account_id,
            transactions=self._window(as_of),
            descriptions=self.descriptions,
            window=(as_of - LOOKBACK, as_of + FOLLOW_UP),
            max_transfers=MAX_TRANSFERS,
            must_include=must_include,
        )
        trace_view = (
            _trace_view(self.transactions, disputed_tx_id, self.tracer)
            if disputed_tx_id is not None
            else None
        )
        evidence = CaseEvidence.model_validate(
            {
                **evidence.model_dump(),
                "risk_probability": score["probability"],
                "reason_codes": tuple(reason["feature"] for reason in score["reasons"]),
                "trace_summary": None
                if trace_view is None
                else {k: v for k, v in trace_view.items() if k != "hops"},
            }
        )
        case_file = template_case_file(evidence)
        check = check_case_file(case_file, evidence)
        alert_cut = alert_count(ranked.height, self.budget)
        return {
            "case_id": case_id,
            "kind": "disputed" if disputed_tx_id is not None else "alerted",
            "account_id": account_id,
            "as_of": as_of.date().isoformat(),
            "score": score,
            "rank": int(row["rank"]),
            "scored_accounts": ranked.height,
            "alerted_at_budget": int(row["rank"]) <= alert_cut,
            "truth": {
                "confirmed_mule_within_horizon": bool(row["label"]),
                "already_active_at_as_of": bool(row["already_active"]),
            },
            "evidence": evidence.model_dump(mode="json"),
            "trace": trace_view,
            "case_file": case_file.model_dump(),
            "checker": {
                "passed": check.passed,
                "violations": [v.__dict__ for v in check.violations],
            },
        }

    def _window(self, as_of: datetime) -> pl.DataFrame:
        start, end = as_of - LOOKBACK, as_of + FOLLOW_UP
        return self.transactions.filter(pl.col("timestamp").is_between(start, end)).collect()

    def alerted(self, as_of: datetime, count: int) -> list[tuple[int, datetime, None]]:
        """``count`` accounts at evenly spaced ranks across the day's alert list.

        Spacing them out shows the queue as the analyst works it, false positives included,
        instead of only its saturated top.
        """
        ranked = _ranked(self._snapshot(as_of), self.artifact)
        cut = alert_count(ranked.height, self.budget)
        ranks = sorted({round(1 + i * (cut - 1) / max(count - 1, 1)) for i in range(count)})
        chosen = ranked.filter(pl.col("rank").is_in(ranks))
        return [(int(a), as_of, None) for a in chosen["account_id"]]

    def disputed(
        self, disputes: pl.DataFrame, first: datetime, last: datetime, count: int
    ) -> list[tuple[int, datetime, int]]:
        """Receivers of accepted disputes between two snapshots, scored at the start of that day.

        Accounts that did not exist yet at that snapshot are skipped: there is no score to show.
        """
        times = self.transactions.select("tx_id", "timestamp").collect()
        rows = (
            disputes.filter(pl.col("outcome") == "accepted")
            .join(times, on="tx_id")
            .filter(pl.col("timestamp").is_between(first, last + timedelta(days=1), closed="left"))
            .sort("timestamp", "tx_id")
        )
        chosen = []
        for row in rows.iter_rows(named=True):
            as_of = row["timestamp"].replace(hour=0, minute=0, second=0, microsecond=0)
            scored = self._snapshot(as_of)["account_id"]
            if int(row["receiver_id"]) in set(scored.to_list()):  # the account existed then
                chosen.append((int(row["receiver_id"]), as_of, int(row["tx_id"])))
        return chosen[:count]
