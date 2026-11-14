# Business case

<!-- Rendered from docs/templates/business_case.md by `muletrace docs render`. Figures
     come from configs/calibration and docs/generated; do not edit numbers by hand. -->

## The user

A fraud or AML analyst at a mid-size payment provider, working on the **receiving side** of
instant payments. The provider holds the accounts that receive money. When a scam victim's bank
reports a fraudulent transfer, it is this provider that has to decide quickly whether to block
the funds, and it is this provider whose accounts are rented or recruited as **money mules**.

Brazil's Pix is the first market and the narrative anchor. The same problem exists under UK
Faster Payments (APP fraud reimbursement), US Nacha rules on incoming credits and the EU
Instant Payments Regulation; MuleTrace maps to those regimes but implements none of them.

## The problem in numbers

All figures below come from the Banco Central do Brasil (BCB) open-data service
*Estatísticas de Fraude no Pix (MED)* (endpoint `Pix_DadosAbertos/EstatisticasFraudesPix`),
accessed on 2026-11-09 (UTC), summed over the
12 complete months from October 2025 to September 2026. The figures
are frozen in
[`configs/calibration/bcb_public_figures.yaml`](../configs/calibration/bcb_public_figures.yaml)
by `scripts/fetch_bcb_calibration.py`. MED (*Mecanismo Especial de Devolução*) is the Pix special
return mechanism used when a payer reports fraud.

| Measure (Oct 2025 – Sep 2026) | Value |
|---|---|
| Pix transfers disputed through MED | 38,325,403 |
| Disputes accepted by the receiving institution | 3,505,363 |
| Value of accepted disputes | R$ 7.94 billion |
| Share of the accepted value actually returned (full or partial) | 12.0% |
| Share of the accepted value **not** returned because the account had insufficient balance | 49.8% |
| Accepted disputes per 100,000 Pix transfers (median of the monthly figures) | 4.31 |

The BCB's own presentation of MED 2.0 (Circuito Pix, 14 October 2025) states the same
diagnosis: in 2025 an average of 9.3% of the disputed value was recovered, blocking and
return happened only at the first receiving account, and fraud proceeds are quickly spread
across other accounts. MED 2.0 (Resolução BCB nº 493, published 28 August 2025) adds tracing
beyond the first account.

Read together, these numbers say one thing: **by the time a dispute arrives, the money has
usually left the first account.** Half of the accepted value could not be returned because
the balance was already gone. The receiving provider wins only if it acts *before* the
dispute, on accounts that behave like mules, and if it can follow the money when a dispute
does arrive.

## The decision MuleTrace supports

Every day the analyst team can review a fixed number of accounts. MuleTrace changes three
decisions:

1. **Which receiving accounts to review today** (the alert queue), under a fixed alert budget.
2. **Where a disputed transfer went next**, and how much is still recoverable at each hop.
3. **What the case file says**, with every claim tied to a transaction ID, so that the analyst
   approves an action (hold, monitor, close) in minutes instead of rebuilding the evidence.

The full problem → decision → action → impact map is in [decision_map.md](decision_map.md).

## The alert budget

The budget is expressed as **alerts per 10,000 scored accounts per day**, because it is the
analyst team's capacity, not the model, that sets it.

- Scored population: accounts that received at least one transfer in the seven days before
  the as-of time and are not already confirmed as mules.
- Default budget: **20 alerts per 10,000 accounts per day** (assumption A1 below).
- On the HI-Small hold-out snapshots, between
  25.51 and
  29.20 accounts per
  10,000 are confirmed as mules within the two-day horizon (see
  [eval_report.md](eval_report.md)), so a budget of 20 forces real prioritisation: even a perfect
  ranking cannot alert on every mule.
- Results are always reported over a range of budgets (5, 10, 20, 50 and 100 per 10,000), so
  a reader with a different capacity can read off their own operating point.

## Costs of error

No public source gives the cost of an analyst review or of a missed mule for a Brazilian
payment provider, so MuleTrace does not invent currency amounts. Costs are expressed in
**review units**: one false positive costs one analyst review (C_FP = 1). A missed mule costs
C_FN review units, and the expected-cost curve is reported for a range of C_FN values.

| Error | Who pays | How it is modelled |
|---|---|---|
| False positive (legitimate account alerted) | The analyst team (review time) and the customer (friction, possible temporary hold) | C_FP = 1 review unit |
| False negative (mule not alerted) | The scam victim first, then the provider through reimbursement rules, regulatory exposure and reputation | C_FN ∈ {10, 50, 100, 500} review units (assumption A2) |

"Value detected" is the simulated illicit inflow received by the mules that were alerted. It is
synthetic, always labelled as such and never presented as money saved.

## Why a learned score should beat rules

A mid-size provider typically runs threshold rules: many distinct senders (fan-in), money
forwarded within 24 hours (pass-through), very young accounts and newly registered keys. These
rules are cheap and explainable, and MuleTrace keeps them as the baseline. Their weaknesses are
structural:

- each rule looks at one signal at a time, while mule behaviour is a combination (moderate
  fan-in *and* fast forwarding *and* a young account);
- thresholds are tuned once and decay as behaviour shifts;
- they ignore the network: an account that receives from accounts already confirmed as mules
  is suspicious even if its own volumes are unremarkable.

A gradient-boosted model on point-in-time tabular and graph features can combine these signals
and rank accounts, which is exactly what a fixed budget needs. Whether it actually wins, and by
how much, is measured in [eval_report.md](eval_report.md) against the rules on the same
temporal hold-out, with confidence intervals. If it does not win, the report says so.

## Assumptions

Every parameter that is not sourced is listed here and kept in configuration files, so it can
be changed and its effect measured.

| ID | Assumption | Default | Where it lives |
|---|---|---|---|
| A1 | Analyst capacity, alerts per 10,000 scored accounts per day | 20 | `configs/evaluation.yaml` |
| A2 | Cost of a missed mule, in review units | 10, 50, 100, 500 | `configs/evaluation.yaml` |
| A3 | Delay between a mule's first illicit inflow and its confirmation | 1 day | `configs/labels.yaml` |
| A4 | Prediction horizon | 2 days | `configs/labels.yaml` |
| A5 | Tracing parameters (maximum hops, hop window, minimum amount) | see `configs/tracer.yaml` | `configs/tracer.yaml` |

MED 2.0 names its tracing parameters (`MinTransactionAmount`, `MaxTransactions`, `HopWindow`,
`MaxHops`) but the official material reviewed does not publish their values. MuleTrace keeps
them configurable and describes its defaults as assumptions, never as official rules.

## What MuleTrace is not

- It is not in production and is not used by any bank or payment provider.
- It does not implement MED 2.0 and is not "BCB compliant"; the tracer is *inspired by* it.
- Its drafted case files are not accepted by COAF (Conselho de Controle de Atividades
  Financeiras, Brazil's financial intelligence unit) or any other authority.
- It does not process real Pix data. Every result comes from synthetic data.
