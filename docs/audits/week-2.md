# Audit — week 2: features, models and honest validation

Date: 2026-11-09. Scope: everything merged for tag `v0.1.0`. Model results are not repeated
here; they live in [eval_report.md](../eval_report.md), rendered from `docs/generated/`.

## 1. Gate results

Local run of every gate CI runs, on the merged branch:

| Gate | Result |
|---|---|
| ruff lint and format | pass |
| mypy `--strict` on `src/` | pass |
| pytest (unit, property, data, model, integration) | 137 passed |
| Coverage (line and branch) on `src/` | 99.54% (floor 85%) |
| xenon (no block above B, module and average A) | pass |
| vulture, deptry, bandit, pip-audit | pass |
| Authorship scan over all commits | pass |

## 2. Coverage and complexity

New critical modules (`asof`, `graph_features`, `backtest`, `bootstrap`, `cost_curve`,
`reporting`) are covered by unit, property and integration tests; overall line and branch
coverage is 99.54%. One module hit the complexity limit during the week and was
refactored before merging: `serialization` (module grade B to A).

## 3. Performance and cost

| Measure | Result | Budget |
|---|---|---|
| Feature build, HI-Small, 8 snapshots | 28.2 s, 2,495 MiB peak | under 10 minutes and 8 GB: **met** |
| Backtest, LI-Small, full ladder and report | 834.2 s, 2,675 MiB peak | none set |
| Transaction-level check, both datasets | 227.7 s, 2,853 MiB peak | none set |
| Label-delay sweep, HI-Small | 1,203.9 s, 4,367 MiB peak | none set |

Cloud cost this week: US$0 (nothing deployed).

## 4. Leakage review

| What could leak | Control | Test |
|---|---|---|
| Graph built with future edges | Edges come from `history_before` only | Hypothesis: appending future rows never changes graph features |
| Neighbour labels confirmed after the as-of time | Only `confirmed_at <= as_of` counts | Explicit test with a late confirmation; property test over random delays |
| Training labels confirmed after the test time | `with_known_labels(frame, test_at)` in every fold | Unit test; fold construction test |
| Hyper-parameters chosen on the hold-out | Search on the first fold's validation snapshot only, then frozen | Visible in `chosen_params` and the run log |
| Calibrator fitted on test data | Isotonic map fitted on each fold's validation snapshot | Backtest code path; integration test |
| Rules tuned on the hold-out | Thresholds chosen on the fold's training and validation snapshots | `tuned_rules` per fold in the report |
| Transaction-level features using the current or later rows | Rolling windows closed on the left; alignment guard | Hypothesis: appending later transactions never changes earlier features |
| Outcome columns reaching a model | `model_features` is the only training list | Test: no overlap between features and outcome or key columns |

## 5. Code I would not want to defend yet, and the fix

- **Isotonic calibration saturates at 1.0** for the highest scores, because every validation
  account in that range was a mule. Showing an analyst "100%" is over-confident. Fix (week 3,
  serving): cap displayed probabilities and always show the rank next to them; consider
  smoothing the top bin.
- **The value-detected metric is dominated by a few huge AMLworld amounts.** Value share jumps
  between budgets when one large account enters the alerted set. It is reported because the
  build plan asks for it, but recall and precision are the decision metrics.
- **Rules tuning overfits on LI-Small** (tuned rules are worse than hand-set on the hold-out).
  This is a finding, not a bug, and it stays in the report.
- **Single seed.** Bootstrap intervals cover account sampling, not training randomness. A
  multi-seed run is cheap and is listed as a debt.
- **The pipeline runs folds sequentially in one process.** Fine at this size; the SageMaker job
  in week 3 runs the same code.

## 6. Decisions and debts

Decisions: [ADR-007](../adr/007-graph-features.md) graph features (components dropped after
measurement), [ADR-008](../adr/008-experiment-tracking.md) experiment tracking.

Process changes:

- Published documents with numbers are rendered from templates (`muletrace docs render`); a test
  fails if a committed document differs from its rendering, so every number is traceable to
  `docs/generated/` or `configs/calibration/`.
- Background runs now use `set -o pipefail`: one failed run had been reported as successful
  because a `grep` at the end of the pipe returned zero.

Debts accepted on purpose: single seed; probability cap deferred to serving; the HI-Small
backtest duration was not captured in a clean run.

Open items carried from week 1: AWS account setup and budgets (owner action); pushing the
reviewed history to GitHub.
