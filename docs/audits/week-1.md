# Audit — week 1: foundation, data and the business case

Date: 2026-11-09. Scope: everything merged into `main` up to the rules baseline and the EDA.

## 1. Gate results

Local run of every gate CI runs (`make check` equivalent), on the merged branch:

| Gate | Result |
|---|---|
| ruff lint and format | pass (62 files) |
| mypy `--strict` on `src/` | pass (24 source files), also with `--platform linux` |
| pytest | 77 passed |
| Coverage (line and branch) | 100.00% on `src/` (floor 85%) |
| xenon (no block above B, average A) | pass, average complexity A (1.73) |
| vulture | pass |
| deptry | pass |
| bandit | pass |
| pip-audit | no known vulnerabilities |
| Authorship scan over all commits | pass |
| gitleaks | runs in CI (container); not run locally because Docker was not running |

On GitHub, the first push to `main` failed only in the secrets step (the marketplace gitleaks
action cannot diff a first push); the fix runs the pinned gitleaks container over the full
history and passed in PR #1 together with every other job.

## 2. Coverage and complexity

Coverage has been 99–100% all week; it reached 100% once tests were added for the CLI paths.
The one function that reached complexity grade C (`parse_patterns`) was refactored into a small
state machine before it was merged. Platform-specific branches of `muletrace.perf` are excluded
from coverage because each runs on one operating system only.

## 3. Performance and cost

| Stage | Wall time | Peak memory |
|---|---:|---:|
| Ingestion, both datasets | 13.4 s | 2,510 MiB |
| Pix layer, both datasets | 3.8 s | 1,657 MiB |
| Rules baseline, 6 snapshots | 5.2 s | 1,349 MiB |

All within the laptop budget (the feature-build budget of 10 minutes and 8 GB is measured next
week). Cloud cost this week: US$0, because nothing has been deployed (see section 6).

## 4. Leakage review

| What could leak | How it is prevented | How it is tested |
|---|---|---|
| Features reading rows at or after the as-of time | Every feature goes through `history_before` (`timestamp < t`) | Hypothesis: appending random future rows never changes flow aggregates or account age |
| Using the moment a mule *became* one instead of when it was *confirmed* | `labels_at` and the population read `confirmed_at` only | Population never contains accounts confirmed at or before *t* (property test) |
| Training labels confirmed after training time | `labels_at(..., known_by=cutoff)` | Property test over random delays and cut-offs |
| Exchange rates estimated on all rows | Rates are a static property of the simulator (ADR-005) | Relative IQR below 1e-5 for every fiat currency |
| Pix-layer fields built from labels (disputes, DICT markings) | Excluded from model features (ADR-006); key registration is label-independent by design | Simulator test: Pix transfers never carry the laundering label |
| `account_id` order | Assigned by lexicographic key, which encodes the bank | Not used as a feature; to be checked in the feature list next week |
| The post-period tail | Last snapshot is 9 September, whose horizon ends inside the primary period | Config test on `evaluation.yaml` |

## 5. Code I would not want to defend yet, and the fix

- **The rules baseline is nearly random** (average precision about 0.003 against a prevalence of
  about 0.0025 on the HI-Small hold-out). The EDA explains why: account age and forwarding speed
  do not separate mules in AMLworld, and the fan-in threshold is too high. Beating it would prove
  nothing. Fix (week 2): add a *tuned* rules baseline whose thresholds are chosen on the training
  snapshots only, and compare the model against the stronger of the two.
- **`cli.py` keeps growing.** Every command is a thin adapter, but the module will pass 300 lines
  in week 2. Fix: split commands into one module per group when that happens.
- **Synthetic descriptions are built through a Python list** of about 700,000 strings. It costs a
  fraction of the 3.8 s Pix-layer run, so it stays; it is noted here so nobody copies the pattern
  into a hot path.
- **`first_seen` is computed over the whole table** and filtered by the as-of time afterwards.
  It is correct (the property test proves it) but subtle; the docstring explains why.

## 6. Decisions and debts

Decisions: [ADR-001](../adr/001-scope.md) scope, [ADR-002](../adr/002-region-and-services.md)
region and services, [ADR-003](../adr/003-no-agentcore-in-v1.md) no AgentCore,
[ADR-004](../adr/004-identifiers-and-data-layout.md) identifiers and layout,
[ADR-005](../adr/005-exchange-rates-from-the-data.md) exchange rates,
[ADR-006](../adr/006-target-and-validation-design.md) target and validation.

Findings recorded on purpose:

- The Kaggle description says the post-period tail is all laundering; in the downloaded version
  it is 655 of 1,108 transactions in HI-Small. Reported in the data card.
- The Pix layer matches the public dispute rate, rejection share and key-type mix, but not the
  average ticket, because AMLworld amounts are not rescaled. Reported in the data card.

Open items against the week-1 acceptance criteria:

| Criterion | Status |
|---|---|
| CI green | Green on GitHub for the scaffold (PR #1); the rest of the week's history is green locally and is pushed once PR #1 is reviewed |
| Data reproducible from a clean clone | `make data` + manifest check; verified from a fresh clone of the repository against the local raw files |
| Data card complete | Done |
| Baseline scored on a temporal hold-out | Done (hand-set rules); tuned rules follow in week 2 |
| Budgets active | **Not done.** AWS account setup (root MFA, Identity Center user, US$15 budget with alerts, US$20 budget action, Cost Anomaly Detection, Bedrock model access, CDK bootstrap, GitHub OIDC role) needs the owner's AWS account and is listed in the README as an owner action |
| First weekly audit | This document |
