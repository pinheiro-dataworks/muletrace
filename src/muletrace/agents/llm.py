"""Model clients: the Bedrock Converse API, and a scripted client for tests.

Agents talk to a :class:`ModelClient`. The Bedrock client sends the Converse request (with tool
definitions and, when configured, a Bedrock guardrail) and returns the text, the tool calls and
the token usage. Cost is computed from configured prices, never estimated afterwards.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import Field

from muletrace.config import StrictModel


class ModelPrice(StrictModel):
    """On-demand price in US dollars per 1,000 tokens."""

    input_per_1k: float = Field(ge=0)
    output_per_1k: float = Field(ge=0)


@dataclass
class ModelReply:
    """One model turn."""

    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    guardrail_intervened: bool = False
    raw_message: dict[str, Any] = field(default_factory=dict)


class ModelClient(Protocol):
    """Anything that can answer a Converse-style request."""

    model_id: str

    def converse(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] = (),
        max_tokens: int = 1024,
    ) -> ModelReply:
        """Send messages and return the model's reply."""


@dataclass
class Usage:
    """Token and cost accounting for one case."""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    latency_ms: float = 0.0
    guardrail_interventions: int = 0
    cost_usd: float = 0.0

    def add(self, reply: ModelReply, price: ModelPrice | None) -> None:
        """Accumulate one reply."""
        self.input_tokens += reply.input_tokens
        self.output_tokens += reply.output_tokens
        self.calls += 1
        self.latency_ms += reply.latency_ms
        self.guardrail_interventions += int(reply.guardrail_intervened)
        if price is not None:
            self.cost_usd += (
                reply.input_tokens * price.input_per_1k + reply.output_tokens * price.output_per_1k
            ) / 1000

    @property
    def total_tokens(self) -> int:
        """Input plus output tokens."""
        return self.input_tokens + self.output_tokens


@dataclass
class BedrockClient:
    """Amazon Bedrock Converse API client."""

    model_id: str
    runtime: Any  # boto3 "bedrock-runtime" client
    guardrail_id: str | None = None
    guardrail_version: str = "DRAFT"

    def converse(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] = (),
        max_tokens: int = 1024,
    ) -> ModelReply:
        """Send one Converse request with temperature 0."""
        request: dict[str, Any] = {
            "modelId": self.model_id,
            "system": [{"text": system}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.0},
        }
        if tools:
            request["toolConfig"] = {"tools": [{"toolSpec": spec} for spec in tools]}
        if self.guardrail_id:
            request["guardrailConfig"] = {
                "guardrailIdentifier": self.guardrail_id,
                "guardrailVersion": self.guardrail_version,
            }
        started = time.perf_counter()
        response = self.runtime.converse(**request)
        latency = (time.perf_counter() - started) * 1000
        message = response["output"]["message"]
        return ModelReply(
            text="".join(block.get("text", "") for block in message["content"]),
            tool_calls=[block["toolUse"] for block in message["content"] if "toolUse" in block],
            input_tokens=int(response["usage"]["inputTokens"]),
            output_tokens=int(response["usage"]["outputTokens"]),
            latency_ms=latency,
            guardrail_intervened=response.get("stopReason") == "guardrail_intervened",
            raw_message=message,
        )


@dataclass
class ScriptedClient:
    """Replays prepared replies in order; records what it was sent. For tests only."""

    replies: list[ModelReply]
    model_id: str = "scripted"
    sent: list[dict[str, Any]] = field(default_factory=list)

    def converse(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: Sequence[dict[str, Any]] = (),
        max_tokens: int = 1024,
    ) -> ModelReply:
        """Return the next prepared reply."""
        self.sent.append(
            {
                "system": system,
                "messages": list(messages),
                "tools": list(tools),
                "max_tokens": max_tokens,
            }
        )
        if not self.replies:
            raise RuntimeError("scripted client has no replies left")
        return self.replies.pop(0)
