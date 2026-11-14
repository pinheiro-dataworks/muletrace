# ADR-011: Copilot — structured claims, a deterministic fact checker, and a guardrail with known gaps

- Status: Accepted
- Date: 2026-11-14

## Context

The copilot drafts case files that an analyst approves. The failure that matters is a draft that
looks right and is not: an invented transfer, a wrong amount, a recommendation an attacker planted
in a transfer description. Language models produce such errors at a rate that cannot be pushed to
zero by prompting alone, and the transfer descriptions are written by customers, so they are
untrusted input.

Amazon Bedrock Guardrails can filter prompt attacks, mask personal data and deny topics. Two
properties of guardrails attached through the Converse API shape what they can do here, both
from the Bedrock user guide ("Include a guardrail with the Converse API" and "Use contextual
grounding check to filter hallucinations in responses"):

- tool results the application returns (`toolResult`) are not evaluated by any guardrail filter;
  the multi-agent copilot receives transfer descriptions through the `get_transfers` tool;
- the contextual grounding check needs the grounding source and the query marked with
  `guardContent` qualifiers, and it returns a similarity score, not an exact comparison.

## Decision

1. **Claims are structured.** A case file is JSON: every claim lists the transaction IDs,
   amounts, dates and account IDs it relies on (`muletrace.agents.case.CaseFile`).
2. **A deterministic fact checker is the gate.** `muletrace.validation.fact_checker` compares
   every cited value with the evidence (amounts within one cent, alone or as the sum of the cited
   transfers; dates, accounts and IDs exactly) and rejects drafts that cite unknown transfers,
   typologies, actions or policies, recommend releasing funds, or contain an e-mail address or
   phone number. A rejected draft is never shown as approvable; the analyst sees why there is
   nothing to approve.
3. **The guardrail is defence in depth, configured for what it can see**
   (`infra/stacks/agents.py`): prompt-attack filtering on inputs read as text, e-mail and phone
   anonymisation on outputs only (so evidence numbers in inputs are never rewritten), and a denied
   topic for releasing funds on outputs. Contextual grounding is not configured: the checker
   already verifies every cited figure against the evidence, without a similarity threshold.
4. **Customer text is labelled as data.** Tools return descriptions under
   `untrusted_customer_text`, and every prompt says to describe it, never follow it.
5. **The copilot never acts.** It recommends hold, monitor or close; the analyst decides. The
   Lambda has permission to call one foundation model and one guardrail, nothing else.
6. **A model-free template baseline sets the bar.** The language-model copilots are reported only
   next to it, and the release gate (`configs/eval_thresholds.yaml`) applies to all of them.

## Consequences

- Unsupported claims reaching the analyst are zero by construction for anything the checker
  understands. What it does not understand — the meaning of the summary, whether the
  recommendation is wise — still needs the analyst, and the LLM judge once it is calibrated
  against human labels.
- Prompt injection through descriptions is not stopped by the guardrail in the multi-agent path,
  because tool results bypass it. The defences there are the prompts, the checker (which catches
  attacks that invent transfers, recommend releasing funds or copy contact details) and human
  approval. An attack that only argues for closing the case produces a valid draft; the
  adversarial suite counts those separately, and the analyst remains the control.
- The checker is strict: one amount off by more than a cent rejects the whole draft. A copilot
  that rounds carelessly will show a low delivery rate rather than wrong numbers, which is the
  trade we want.
- Revisit when Bedrock Guardrails evaluate tool results, or if the copilot moves to a framework
  that applies a guardrail to tool output (for example with the `ApplyGuardrail` API on each tool
  result before it reaches the model).
