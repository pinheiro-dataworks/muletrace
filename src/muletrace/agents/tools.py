"""Tools the evidence agent may call, and their deterministic implementations.

Tools answer from the case evidence and the policy library only; they cannot reach the network or
the raw tables. Results are cached per case, so asking twice costs nothing. Transfer descriptions
are returned in a separate, clearly labelled field, because they are customer-written text and the
place where prompt-injection attempts arrive.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final

from muletrace.agents.case import CaseEvidence
from muletrace.policy.loader import lookup

TOOL_SPECS: Final[tuple[dict[str, Any], ...]] = (
    {
        "name": "get_transfers",
        "description": "List the case account's transfers, largest first.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["in", "out", "both"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["direction"],
            }
        },
    },
    {
        "name": "get_risk_profile",
        "description": "Risk probability, reason codes and fund-flow trace summary of the case.",
        "inputSchema": {"json": {"type": "object", "properties": {}}},
    },
    {
        "name": "lookup_policy",
        "description": "Find regulatory summaries by topic words (for example 'return dispute').",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }
        },
    },
)


@dataclass
class ToolBox:
    """Executes tool calls for one case and caches their results."""

    evidence: CaseEvidence
    cache: dict[str, str] = field(default_factory=dict)
    calls: int = 0

    def run(self, name: str, arguments: dict[str, Any]) -> str:
        """Run one tool call and return its JSON result."""
        key = f"{name}:{json.dumps(arguments, sort_keys=True)}"
        if key not in self.cache:
            self.calls += 1
            self.cache[key] = json.dumps(self._dispatch(name, arguments), default=str)
        return self.cache[key]

    def _dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_transfers":
            return self._transfers(
                str(arguments.get("direction", "both")), int(arguments.get("limit", 20))
            )
        if name == "get_risk_profile":
            return {
                "risk_probability": self.evidence.risk_probability,
                "reason_codes": list(self.evidence.reason_codes),
                "trace_summary": self.evidence.trace_summary,
            }
        if name == "lookup_policy":
            return {
                "policies": [
                    {"id": entry.id, "title": entry.title, "summary": entry.summary}
                    for entry in lookup(str(arguments.get("query", "")))
                ]
            }
        return {"error": f"unknown tool {name!r}"}

    def _transfers(self, direction: str, limit: int) -> dict[str, Any]:
        selected = [t for t in self.evidence.transfers if direction in {"both", t.direction}]
        selected = sorted(selected, key=lambda t: -t.amount_usd)[: max(1, min(limit, 50))]
        return {
            "transfers": [
                {
                    "tx_id": t.tx_id,
                    "date": t.timestamp.date().isoformat(),
                    "time": f"{t.timestamp:%H:%M}",
                    "direction": t.direction,
                    "counterparty_id": t.counterparty_id,
                    "amount_usd": t.amount_usd,
                    "format": t.payment_format,
                }
                for t in selected
            ],
            "untrusted_customer_text": {
                str(t.tx_id): t.description for t in selected if t.description
            },
        }
