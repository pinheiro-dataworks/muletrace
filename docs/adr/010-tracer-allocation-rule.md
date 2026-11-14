# ADR-010: Tracer allocation rule — tainted money leaves first, oldest first

- Status: Accepted
- Date: 2026-11-13

## Context

A tracer must decide which part of an account's outgoing money is the disputed money. Balances
are not observable, and an account mixes tainted and legitimate funds. Common rules are
first-in-first-out on all funds, pro-rata (each outflow carries the account's tainted share) and
tainted-first. MED 2.0, which inspires the tracer, names its tracing parameters (maximum hops,
hop window, minimum transaction amount, maximum transactions) but its allocation algorithm is not
public.

## Decision

Tainted money leaves first, oldest lot first, and only within the hop window of its arrival.
Untraceable outflows (beyond the hop limit, below the minimum amount, past the transaction cap)
count as having left the trace; whatever no followed outflow consumed stays in the account as
the recoverable estimate. The four parameters live in `configs/tracer.yaml` as assumptions.

## Consequences

- It is the pessimistic case for recovery: it moves as much tainted money onward as transfers
  allow, so blocking requests are sent wide rather than missed.
- Conservation holds exactly and is property-tested: recoverable plus left-the-trace equals the
  disputed amount, no hop carries more than its transfer, and no hop precedes the dispute.
- Measured against AMLworld's labels, precision is low (see `docs/eval_report.md`, section 12):
  the rule attributes tainted money to ordinary outflows. A pro-rata rule is the obvious next
  experiment and would trade coverage for precision.
- The recoverable estimate is an upper bound and is never reported as a recovery rate.
