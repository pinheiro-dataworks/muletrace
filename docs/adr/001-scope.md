# ADR-001: Scope — one user, one workflow, small datasets

- Status: Accepted
- Date: 2026-11-08

## Context

The project has a five-week budget of roughly ten hours per week and a cloud budget of
US$15. A portfolio project that tries to cover every AML use case ends up proving none of them.
AMLworld ships six transaction files; the Large ones hold around 175–180 million transactions
each and the Medium ones over 30 million.

## Decision

- One user: a fraud or AML analyst on the receiving side of instant payments.
- One workflow with three parts: a daily mule-risk score, a fund-flow tracer for disputed
  transfers and an investigation copilot that drafts case files for human approval.
- Data: AMLworld **HI-Small** (main experiments) and **LI-Small** (robustness check under a lower
  illicit ratio). Medium and Large files are not used.
- Synthetic data only. No real Pix, bank or customer data.
- Learned graph embeddings (for example GraphSAGE) are out of scope unless the ablation shows
  that simple graph aggregates and PageRank leave a measurable gap.

## Consequences

- Every experiment runs on a laptop in minutes, so the validation design can be thorough
  (rolling-origin backtest, bootstrap intervals, label-delay sweep) instead of a single split.
- The Small files span only ten days of primary activity. Horizons and windows are therefore
  measured in hours and days, and conclusions about long-term drift cannot be drawn.
- Results cannot be extrapolated to real volumes. The README says so.
