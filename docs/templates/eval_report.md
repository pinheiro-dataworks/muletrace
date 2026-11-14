# Evaluation report

<!-- Rendered from docs/templates/eval_report.md by `muletrace docs render`.
     Every number below is a placeholder resolved against docs/generated/*.yaml;
     a test fails if this file and its template drift apart. Do not edit numbers by hand. -->

All results come from **synthetic data** (IBM AMLworld HI-Small and LI-Small, see the
[data card](data_card.md)). "Value" figures are simulated amounts and never money saved.

## 1. What is evaluated

- **Decision.** Each day the analyst team reviews the top of a ranked queue of receiving
  accounts. The headline budget is **20 alerts per 10,000 scored accounts** (assumption A1 in the
  [business case](business_case.md)); results at 5, 10, 50 and 100 are reported too.
- **Target.** An account is positive at as-of time *t* if it is confirmed as a mule in
  `(t, t + 48 h]`; confirmation arrives 24 hours after the first illicit inflow
  ([ADR-006](adr/006-target-and-validation-design.md)).
- **Validation.** Rolling origin with four folds (test snapshots 6, 7, 8 and 9 September 2022).
  Each fold validates on the snapshot one horizon earlier and trains on every snapshot before
  that, with labels truncated at the test time. The **hold-out** is the pooled 7, 8 and 9
  September snapshots, on which every model is scored.
- **Intervals.** 95% percentile intervals from a paired Poisson bootstrap with
  {{ backtest_HI-Small.bootstrap.replicates | int }} replicates; the same resampling weights are
  applied to every model, so differences have their own intervals.

Prevalence on the hold-out snapshots:

| Snapshot | HI-Small scored | HI-Small positives | per 10,000 | LI-Small scored | LI-Small positives | per 10,000 |
|---|---:|---:|---:|---:|---:|---:|
| 7 Sep | {{ rules_baseline.HI-Small.snapshots.2022-09-07T00:00:00.scored_accounts | int }} | {{ rules_baseline.HI-Small.snapshots.2022-09-07T00:00:00.positives | int }} | {{ rules_baseline.HI-Small.snapshots.2022-09-07T00:00:00.positives_per_10k | f2 }} | {{ rules_baseline.LI-Small.snapshots.2022-09-07T00:00:00.scored_accounts | int }} | {{ rules_baseline.LI-Small.snapshots.2022-09-07T00:00:00.positives | int }} | {{ rules_baseline.LI-Small.snapshots.2022-09-07T00:00:00.positives_per_10k | f2 }} |
| 8 Sep | {{ rules_baseline.HI-Small.snapshots.2022-09-08T00:00:00.scored_accounts | int }} | {{ rules_baseline.HI-Small.snapshots.2022-09-08T00:00:00.positives | int }} | {{ rules_baseline.HI-Small.snapshots.2022-09-08T00:00:00.positives_per_10k | f2 }} | {{ rules_baseline.LI-Small.snapshots.2022-09-08T00:00:00.scored_accounts | int }} | {{ rules_baseline.LI-Small.snapshots.2022-09-08T00:00:00.positives | int }} | {{ rules_baseline.LI-Small.snapshots.2022-09-08T00:00:00.positives_per_10k | f2 }} |
| 9 Sep | {{ rules_baseline.HI-Small.snapshots.2022-09-09T00:00:00.scored_accounts | int }} | {{ rules_baseline.HI-Small.snapshots.2022-09-09T00:00:00.positives | int }} | {{ rules_baseline.HI-Small.snapshots.2022-09-09T00:00:00.positives_per_10k | f2 }} | {{ rules_baseline.LI-Small.snapshots.2022-09-09T00:00:00.scored_accounts | int }} | {{ rules_baseline.LI-Small.snapshots.2022-09-09T00:00:00.positives | int }} | {{ rules_baseline.LI-Small.snapshots.2022-09-09T00:00:00.positives_per_10k | f2 }} |

## 2. Headline: the model ladder at the analyst budget

HI-Small hold-out, 20 alerts per 10,000 scored accounts:

| Model | Recall (95% CI) | Precision | Average precision (95% CI) | Value share |
|---|---:|---:|---:|---:|
| Rules, hand-set thresholds | {{ backtest_HI-Small.bootstrap.recall.rules_hand_set.estimate | pct }} ({{ backtest_HI-Small.bootstrap.recall.rules_hand_set.ci95 | ci }}) | {{ backtest_HI-Small.hold_out.rules_hand_set[alerts_per_10k=20].precision | pct }} | {{ backtest_HI-Small.bootstrap.average_precision.rules_hand_set.estimate | f3 }} ({{ backtest_HI-Small.bootstrap.average_precision.rules_hand_set.ci95 | ci3 }}) | {{ backtest_HI-Small.hold_out.rules_hand_set[alerts_per_10k=20].value_share | pct }} |
| Rules, thresholds tuned on training snapshots | {{ backtest_HI-Small.bootstrap.recall.rules_tuned.estimate | pct }} ({{ backtest_HI-Small.bootstrap.recall.rules_tuned.ci95 | ci }}) | {{ backtest_HI-Small.hold_out.rules_tuned[alerts_per_10k=20].precision | pct }} | {{ backtest_HI-Small.bootstrap.average_precision.rules_tuned.estimate | f3 }} ({{ backtest_HI-Small.bootstrap.average_precision.rules_tuned.ci95 | ci3 }}) | {{ backtest_HI-Small.hold_out.rules_tuned[alerts_per_10k=20].value_share | pct }} |
| LightGBM, behaviour features | {{ backtest_HI-Small.bootstrap.recall.lgbm_tabular.estimate | pct }} ({{ backtest_HI-Small.bootstrap.recall.lgbm_tabular.ci95 | ci }}) | {{ backtest_HI-Small.hold_out.lgbm_tabular[alerts_per_10k=20].precision | pct }} | {{ backtest_HI-Small.bootstrap.average_precision.lgbm_tabular.estimate | f3 }} ({{ backtest_HI-Small.bootstrap.average_precision.lgbm_tabular.ci95 | ci3 }}) | {{ backtest_HI-Small.hold_out.lgbm_tabular[alerts_per_10k=20].value_share | pct }} |
| **LightGBM, behaviour + graph** | **{{ backtest_HI-Small.bootstrap.recall.lgbm_tabular_graph.estimate | pct }}** ({{ backtest_HI-Small.bootstrap.recall.lgbm_tabular_graph.ci95 | ci }}) | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=20].precision | pct }} | **{{ backtest_HI-Small.bootstrap.average_precision.lgbm_tabular_graph.estimate | f3 }}** ({{ backtest_HI-Small.bootstrap.average_precision.lgbm_tabular_graph.ci95 | ci3 }}) | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=20].value_share | pct }} |

Paired differences (HI-Small hold-out, 20 alerts per 10,000):

| Comparison | Recall difference (95% CI) | Average-precision difference (95% CI) |
|---|---:|---:|
| Graph model minus tuned rules | {{ backtest_HI-Small.bootstrap.recall_difference.lgbm_tabular_graph minus rules_tuned.estimate | pct }} ({{ backtest_HI-Small.bootstrap.recall_difference.lgbm_tabular_graph minus rules_tuned.ci95 | ci }}) | {{ backtest_HI-Small.bootstrap.average_precision_difference.lgbm_tabular_graph minus rules_tuned.estimate | f3 }} ({{ backtest_HI-Small.bootstrap.average_precision_difference.lgbm_tabular_graph minus rules_tuned.ci95 | ci3 }}) |
| Graph model minus behaviour-only model (graph ablation) | {{ backtest_HI-Small.bootstrap.recall_difference.lgbm_tabular_graph minus lgbm_tabular.estimate | pct }} ({{ backtest_HI-Small.bootstrap.recall_difference.lgbm_tabular_graph minus lgbm_tabular.ci95 | ci }}) | {{ backtest_HI-Small.bootstrap.average_precision_difference.lgbm_tabular_graph minus lgbm_tabular.estimate | f3 }} ({{ backtest_HI-Small.bootstrap.average_precision_difference.lgbm_tabular_graph minus lgbm_tabular.ci95 | ci3 }}) |
| Tuned rules minus hand-set rules | {{ backtest_HI-Small.bootstrap.recall_difference.rules_tuned minus rules_hand_set.estimate | pct }} ({{ backtest_HI-Small.bootstrap.recall_difference.rules_tuned minus rules_hand_set.ci95 | ci }}) | {{ backtest_HI-Small.bootstrap.average_precision_difference.rules_tuned minus rules_hand_set.estimate | f3 }} ({{ backtest_HI-Small.bootstrap.average_precision_difference.rules_tuned minus rules_hand_set.ci95 | ci3 }}) |

**Reading.** The model beats the rules by a wide margin and the interval of the difference is far
from zero. Graph features add a smaller but clearly positive amount. Tuning the rules' thresholds
on training snapshots does not help: their signals (account age, forwarding speed, fan-in) barely
separate mules in AMLworld (see `notebooks/01_eda.ipynb`), so moving thresholds cannot fix them.
Beating such a weak baseline proves little on its own; the stronger evidence is the absolute level
(about one alert in four is a mule, at a prevalence of about one in four hundred) and the slices
in section 6.

## 3. Robustness: LI-Small (lower illicit ratio)

| Model | Recall at 20 (95% CI) | Average precision (95% CI) |
|---|---:|---:|
| Rules, hand-set | {{ backtest_LI-Small.bootstrap.recall.rules_hand_set.estimate | pct }} ({{ backtest_LI-Small.bootstrap.recall.rules_hand_set.ci95 | ci }}) | {{ backtest_LI-Small.bootstrap.average_precision.rules_hand_set.estimate | f3 }} ({{ backtest_LI-Small.bootstrap.average_precision.rules_hand_set.ci95 | ci3 }}) |
| Rules, tuned | {{ backtest_LI-Small.bootstrap.recall.rules_tuned.estimate | pct }} ({{ backtest_LI-Small.bootstrap.recall.rules_tuned.ci95 | ci }}) | {{ backtest_LI-Small.bootstrap.average_precision.rules_tuned.estimate | f3 }} ({{ backtest_LI-Small.bootstrap.average_precision.rules_tuned.ci95 | ci3 }}) |
| LightGBM, behaviour | {{ backtest_LI-Small.bootstrap.recall.lgbm_tabular.estimate | pct }} ({{ backtest_LI-Small.bootstrap.recall.lgbm_tabular.ci95 | ci }}) | {{ backtest_LI-Small.bootstrap.average_precision.lgbm_tabular.estimate | f3 }} ({{ backtest_LI-Small.bootstrap.average_precision.lgbm_tabular.ci95 | ci3 }}) |
| LightGBM, behaviour + graph | {{ backtest_LI-Small.bootstrap.recall.lgbm_tabular_graph.estimate | pct }} ({{ backtest_LI-Small.bootstrap.recall.lgbm_tabular_graph.ci95 | ci }}) | {{ backtest_LI-Small.bootstrap.average_precision.lgbm_tabular_graph.estimate | f3 }} ({{ backtest_LI-Small.bootstrap.average_precision.lgbm_tabular_graph.ci95 | ci3 }}) |

Graph ablation on LI-Small: recall difference
{{ backtest_LI-Small.bootstrap.recall_difference.lgbm_tabular_graph minus lgbm_tabular.estimate | pct }}
({{ backtest_LI-Small.bootstrap.recall_difference.lgbm_tabular_graph minus lgbm_tabular.ci95 | ci }}),
average-precision difference
{{ backtest_LI-Small.bootstrap.average_precision_difference.lgbm_tabular_graph minus lgbm_tabular.estimate | f3 }}
({{ backtest_LI-Small.bootstrap.average_precision_difference.lgbm_tabular_graph minus lgbm_tabular.ci95 | ci3 }}).
Tuned minus hand-set rules:
{{ backtest_LI-Small.bootstrap.recall_difference.rules_tuned minus rules_hand_set.estimate | pct }}
({{ backtest_LI-Small.bootstrap.recall_difference.rules_tuned minus rules_hand_set.ci95 | ci }}).

**Reading.** With fewer mules everything is harder, but the ordering holds. The graph gain in
recall at the budget is not distinguishable from zero on LI-Small (its interval touches zero),
while its gain in average precision is. Tuning the rules on training snapshots made them *worse*
on the hold-out: the thresholds chosen on a handful of training days did not transfer, a small
example of why a rules engine tuned by hand needs the same temporal validation as a model.

## 4. Stability across folds (HI-Small)

Recall at 20 alerts per 10,000, per test snapshot:

| Model | 6 Sep | 7 Sep | 8 Sep | 9 Sep |
|---|---:|---:|---:|---:|
| Rules, tuned | {{ backtest_HI-Small.per_fold.rules_tuned.2022-09-06T00:00:00.budgets[alerts_per_10k=20].recall | pct }} | {{ backtest_HI-Small.per_fold.rules_tuned.2022-09-07T00:00:00.budgets[alerts_per_10k=20].recall | pct }} | {{ backtest_HI-Small.per_fold.rules_tuned.2022-09-08T00:00:00.budgets[alerts_per_10k=20].recall | pct }} | {{ backtest_HI-Small.per_fold.rules_tuned.2022-09-09T00:00:00.budgets[alerts_per_10k=20].recall | pct }} |
| LightGBM, behaviour | {{ backtest_HI-Small.per_fold.lgbm_tabular.2022-09-06T00:00:00.budgets[alerts_per_10k=20].recall | pct }} | {{ backtest_HI-Small.per_fold.lgbm_tabular.2022-09-07T00:00:00.budgets[alerts_per_10k=20].recall | pct }} | {{ backtest_HI-Small.per_fold.lgbm_tabular.2022-09-08T00:00:00.budgets[alerts_per_10k=20].recall | pct }} | {{ backtest_HI-Small.per_fold.lgbm_tabular.2022-09-09T00:00:00.budgets[alerts_per_10k=20].recall | pct }} |
| LightGBM, behaviour + graph | {{ backtest_HI-Small.per_fold.lgbm_tabular_graph.2022-09-06T00:00:00.budgets[alerts_per_10k=20].recall | pct }} | {{ backtest_HI-Small.per_fold.lgbm_tabular_graph.2022-09-07T00:00:00.budgets[alerts_per_10k=20].recall | pct }} | {{ backtest_HI-Small.per_fold.lgbm_tabular_graph.2022-09-08T00:00:00.budgets[alerts_per_10k=20].recall | pct }} | {{ backtest_HI-Small.per_fold.lgbm_tabular_graph.2022-09-09T00:00:00.budgets[alerts_per_10k=20].recall | pct }} |

The model improves as more training snapshots become available (the 6 September fold trains on
two days only) and the graph model is ahead of the behaviour-only model on every fold.

## 5. Recall across budgets (HI-Small hold-out)

| Alerts per 10,000 | 5 | 10 | 20 | 50 | 100 |
|---|---:|---:|---:|---:|---:|
| Rules, tuned | {{ backtest_HI-Small.hold_out.rules_tuned[alerts_per_10k=5].recall | pct }} | {{ backtest_HI-Small.hold_out.rules_tuned[alerts_per_10k=10].recall | pct }} | {{ backtest_HI-Small.hold_out.rules_tuned[alerts_per_10k=20].recall | pct }} | {{ backtest_HI-Small.hold_out.rules_tuned[alerts_per_10k=50].recall | pct }} | {{ backtest_HI-Small.hold_out.rules_tuned[alerts_per_10k=100].recall | pct }} |
| LightGBM, behaviour + graph | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=5].recall | pct }} | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=10].recall | pct }} | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=20].recall | pct }} | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=50].recall | pct }} | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=100].recall | pct }} |
| Precision, graph model | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=5].precision | pct }} | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=10].precision | pct }} | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=20].precision | pct }} | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=50].precision | pct }} | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=100].precision | pct }} |

## 6. Where the model wins and where it fails (HI-Small hold-out, graph model)

Recall at 20 alerts per 10,000 among positives:

| Slice | Positives | Recall |
|---|---:|---:|
| Already active at the as-of time | {{ backtest_HI-Small.slices_lgbm_tabular_graph.activity.already active at as-of.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.activity.already active at as-of.recall | pct }} |
| Not yet active at the as-of time | {{ backtest_HI-Small.slices_lgbm_tabular_graph.activity.not yet active.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.activity.not yet active.recall | pct }} |
| Inside a recorded typology: stack | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.STACK.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.STACK.recall | pct }} |
| Scatter-gather | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.SCATTER-GATHER.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.SCATTER-GATHER.recall | pct }} |
| Gather-scatter | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.GATHER-SCATTER.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.GATHER-SCATTER.recall | pct }} |
| Cycle | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.CYCLE.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.CYCLE.recall | pct }} |
| Fan-out | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.FAN-OUT.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.FAN-OUT.recall | pct }} |
| Bipartite | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.BIPARTITE.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.BIPARTITE.recall | pct }} |
| Random | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.RANDOM.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.RANDOM.recall | pct }} |
| Fan-in | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.FAN-IN.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.FAN-IN.recall | pct }} |
| No recorded pattern | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.no pattern.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.no pattern.recall | pct }} |

**Reading.** The score is a detector of **active, not-yet-confirmed** mules, not a predictor of
future recruitment: an account whose first illicit inflow happens after the as-of time has nothing
in its past to give it away. Mules inside a recorded laundering pattern are found far more often
than those whose laundering follows no pattern. Fan-in has very few positives, so its rate is
noisy.

**Value detected is small.** At the headline budget, alerted accounts receive
{{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=20].value_share | pct }} of the
simulated illicit inflow that arrives during the horizon. Most of that money reaches accounts
that were not yet active when scored, which is exactly the slice the model misses. This is the
honest limit of an account-level daily score, and the reason the fund-flow tracer exists.

## 7. Calibration (HI-Small hold-out, graph model)

| Brier score | Value |
|---|---:|
| Raw scores | {{ backtest_HI-Small.calibration.lgbm_tabular_graph.brier_raw | f4 }} |
| After isotonic calibration | {{ backtest_HI-Small.calibration.lgbm_tabular_graph.brier_calibrated | f4 }} |
| Constant equal to the prevalence | {{ backtest_HI-Small.calibration.lgbm_tabular_graph.brier_constant_prevalence | f4 }} |

Mean calibrated probability {{ backtest_HI-Small.calibration.lgbm_tabular_graph.mean_predicted | pct2 }}
against an observed rate of {{ backtest_HI-Small.calibration.lgbm_tabular_graph.observed_rate | pct2 }}.
The isotonic map saturates at 1.0 for the highest scores (every validation account in that range
was a mule), which over-states certainty at the very top; see the week-2 audit.

## 8. Expected cost (HI-Small hold-out, review units)

A false positive costs one review; a missed mule costs C_FN reviews (assumption A2). Costs are
summed over the three hold-out snapshots.

| C_FN | No alerts | Rules (tuned) at budget | Graph model at budget | Graph model, best budget | Graph model, threshold policy |
|---:|---:|---:|---:|---:|---:|
| 10 | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=10].cost_with_no_alerts | int }} | {{ backtest_HI-Small.expected_cost.rules_tuned[missed_mule_cost=10].cost_at_budget | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=10].cost_at_budget | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=10].best_cost | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=10].threshold_policy_cost | int }} |
| 50 | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=50].cost_with_no_alerts | int }} | {{ backtest_HI-Small.expected_cost.rules_tuned[missed_mule_cost=50].cost_at_budget | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=50].cost_at_budget | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=50].best_cost | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=50].threshold_policy_cost | int }} |
| 100 | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=100].cost_with_no_alerts | int }} | {{ backtest_HI-Small.expected_cost.rules_tuned[missed_mule_cost=100].cost_at_budget | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=100].cost_at_budget | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=100].best_cost | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=100].threshold_policy_cost | int }} |
| 500 | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=500].cost_with_no_alerts | int }} | {{ backtest_HI-Small.expected_cost.rules_tuned[missed_mule_cost=500].cost_at_budget | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=500].cost_at_budget | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=500].best_cost | int }} | {{ backtest_HI-Small.expected_cost.lgbm_tabular_graph[missed_mule_cost=500].threshold_policy_cost | int }} |

**Reading.** At every assumed cost the model is cheaper than the rules at the same budget. When a
missed mule costs 10 reviews, the cost-minimising budget is close to the headline 20 per 10,000;
as a miss becomes more expensive, the optimum moves to the largest budget evaluated (200 per
10,000), which says analyst capacity, not the model, becomes the binding constraint. The
calibrated threshold policy needs no budget at all and stays within about 5% of the best fixed
budget up to C_FN = 100; at C_FN = 500 it is cheaper, because it may alert on more accounts than
the largest budget evaluated.

## 9. Label-delay sensitivity (HI-Small hold-out)

Both LightGBM models re-run with the main backtest's hyper-parameters; only the confirmation delay
changes (the horizon stays 48 hours).

| Confirmation delay | Positives | Share already active | Recall, graph model (95% CI) | Recall, behaviour model (95% CI) | AP, graph model |
|---|---:|---:|---:|---:|---:|
| 0 h | {{ delay_sweep_HI-Small.delays.0h.positives | int }} | {{ delay_sweep_HI-Small.delays.0h.already_active_share | pct }} | {{ delay_sweep_HI-Small.delays.0h.recall.lgbm_tabular_graph.estimate | pct }} ({{ delay_sweep_HI-Small.delays.0h.recall.lgbm_tabular_graph.ci95 | ci }}) | {{ delay_sweep_HI-Small.delays.0h.recall.lgbm_tabular.estimate | pct }} ({{ delay_sweep_HI-Small.delays.0h.recall.lgbm_tabular.ci95 | ci }}) | {{ delay_sweep_HI-Small.delays.0h.average_precision.lgbm_tabular_graph.estimate | f3 }} |
| 12 h | {{ delay_sweep_HI-Small.delays.12h.positives | int }} | {{ delay_sweep_HI-Small.delays.12h.already_active_share | pct }} | {{ delay_sweep_HI-Small.delays.12h.recall.lgbm_tabular_graph.estimate | pct }} ({{ delay_sweep_HI-Small.delays.12h.recall.lgbm_tabular_graph.ci95 | ci }}) | {{ delay_sweep_HI-Small.delays.12h.recall.lgbm_tabular.estimate | pct }} ({{ delay_sweep_HI-Small.delays.12h.recall.lgbm_tabular.ci95 | ci }}) | {{ delay_sweep_HI-Small.delays.12h.average_precision.lgbm_tabular_graph.estimate | f3 }} |
| 24 h (default) | {{ delay_sweep_HI-Small.delays.24h.positives | int }} | {{ delay_sweep_HI-Small.delays.24h.already_active_share | pct }} | {{ delay_sweep_HI-Small.delays.24h.recall.lgbm_tabular_graph.estimate | pct }} ({{ delay_sweep_HI-Small.delays.24h.recall.lgbm_tabular_graph.ci95 | ci }}) | {{ delay_sweep_HI-Small.delays.24h.recall.lgbm_tabular.estimate | pct }} ({{ delay_sweep_HI-Small.delays.24h.recall.lgbm_tabular.ci95 | ci }}) | {{ delay_sweep_HI-Small.delays.24h.average_precision.lgbm_tabular_graph.estimate | f3 }} |
| 48 h | {{ delay_sweep_HI-Small.delays.48h.positives | int }} | {{ delay_sweep_HI-Small.delays.48h.already_active_share | pct }} | {{ delay_sweep_HI-Small.delays.48h.recall.lgbm_tabular_graph.estimate | pct }} ({{ delay_sweep_HI-Small.delays.48h.recall.lgbm_tabular_graph.ci95 | ci }}) | {{ delay_sweep_HI-Small.delays.48h.recall.lgbm_tabular.estimate | pct }} ({{ delay_sweep_HI-Small.delays.48h.recall.lgbm_tabular.ci95 | ci }}) | {{ delay_sweep_HI-Small.delays.48h.average_precision.lgbm_tabular_graph.estimate | f3 }} |
| 72 h | {{ delay_sweep_HI-Small.delays.72h.positives | int }} | {{ delay_sweep_HI-Small.delays.72h.already_active_share | pct }} | {{ delay_sweep_HI-Small.delays.72h.recall.lgbm_tabular_graph.estimate | pct }} ({{ delay_sweep_HI-Small.delays.72h.recall.lgbm_tabular_graph.ci95 | ci }}) | {{ delay_sweep_HI-Small.delays.72h.recall.lgbm_tabular.estimate | pct }} ({{ delay_sweep_HI-Small.delays.72h.recall.lgbm_tabular.ci95 | ci }}) | {{ delay_sweep_HI-Small.delays.72h.average_precision.lgbm_tabular_graph.estimate | f3 }} |

**Reading.** The result runs against the naive expectation that later labels make the problem
harder. With no delay, every positive becomes a mule *after* the as-of time, nothing in its past
gives it away, and recall at the budget collapses to
{{ delay_sweep_HI-Small.delays.0h.recall.lgbm_tabular_graph.estimate | pct }}. As the delay grows,
a larger share of the positives is already active when scored, and the score's real job (finding
active, unconfirmed mules) has more to work with; recall peaks at 48 hours. It falls back at
72 hours; two plausible reasons, not tested here, are that confirmed-neighbour features are staler
and that fewer training labels are confirmed by each test time. Graph features add recall at
every delay except zero, where nothing is detectable. The 24-hour row reproduces the main backtest
exactly (same data, seed and hyper-parameters).

**What it means for the decision.** The slower confirmations are in practice, the more a daily
score is worth, and its value lies in shortening the time an active mule stays unconfirmed, not
in predicting recruitment.

## 10. External check: AMLworld's transaction-level task

The paper's own task classifies transactions on a 60/20/20 temporal split and reports the F1
score of the laundering class. MuleTrace's version uses causal 24-hour aggregates of the sender,
the receiver and the pair, one seed, and an F1-maximising threshold chosen on the validation 20%.

| Dataset | MuleTrace test F1 | Precision | Recall | Paper: GIN | Paper: PNA | Paper: GFP + LightGBM |
|---|---:|---:|---:|---:|---:|---:|
| HI-Small | {{ transaction_level_check.HI-Small.test.f1_percent | f2 }}% | {{ transaction_level_check.HI-Small.test.precision | pct }} | {{ transaction_level_check.HI-Small.test.recall | pct }} | {{ transaction_level_check.HI-Small.paper_reference.GIN | f2 }}% | {{ transaction_level_check.HI-Small.paper_reference.PNA | f2 }}% | {{ transaction_level_check.HI-Small.paper_reference.GFP + LightGBM | f2 }}% |
| LI-Small | {{ transaction_level_check.LI-Small.test.f1_percent | f2 }}% | {{ transaction_level_check.LI-Small.test.precision | pct }} | {{ transaction_level_check.LI-Small.test.recall | pct }} | {{ transaction_level_check.LI-Small.paper_reference.GIN | f2 }}% | {{ transaction_level_check.LI-Small.paper_reference.PNA | f2 }}% | {{ transaction_level_check.LI-Small.paper_reference.GFP + LightGBM | f2 }}% |

Paper figures: Altman et al., arXiv:2306.16424, Table 2 (means over several runs; MuleTrace
reports a single run, so its numbers carry no interval).

**Reading.** The data handling reproduces the paper's ordering: results land above the paper's
plain GIN and below its graph-feature-preprocessed gradient boosting, on both datasets. The gap to
GFP + LightGBM is the price of using simple window aggregates instead of a dedicated graph-pattern
feature generator. These are modest numbers, reported as they are.

## 11. What drives the score

Mean absolute SHAP contribution on the HI-Small hold-out (graph model), top five:
{{ backtest_HI-Small.feature_importance_lgbm_tabular_graph[0].feature }},
{{ backtest_HI-Small.feature_importance_lgbm_tabular_graph[1].feature }},
{{ backtest_HI-Small.feature_importance_lgbm_tabular_graph[2].feature }},
{{ backtest_HI-Small.feature_importance_lgbm_tabular_graph[3].feature }} and
{{ backtest_HI-Small.feature_importance_lgbm_tabular_graph[4].feature }}.
The full list is in `docs/generated/backtest_HI-Small.yaml`; reason codes for the top of the
queue are shown in `notebooks/02_error_analysis.ipynb`.

## 12. Fund-flow tracer

Every accepted MED-style dispute in the Pix layer is traced with the parameters in
`configs/tracer.yaml` (maximum {{ tracer_evaluation_HI-Small.config.max_hops }} hops, a
{{ tracer_evaluation_HI-Small.config.hop_window_hours | int }}-hour hop window, transfers of at
least US${{ tracer_evaluation_HI-Small.config.min_transaction_usd | int }}), and scored against
AMLworld's own laundering labels, which follow laundered money through later transfers.

| | HI-Small | LI-Small |
|---|---:|---:|
| Accepted disputes traced | {{ tracer_evaluation_HI-Small.disputes_traced }} | {{ tracer_evaluation_LI-Small.disputes_traced }} |
| Disputes where the money moved on within the window | {{ tracer_evaluation_HI-Small.disputes_with_onward_hops }} | {{ tracer_evaluation_LI-Small.disputes_with_onward_hops }} |
| Deepest hop reached | {{ tracer_evaluation_HI-Small.max_hop_reached }} | {{ tracer_evaluation_LI-Small.max_hop_reached }} |
| Where the money moved: median share of the disputed amount located beyond the first account | {{ tracer_evaluation_HI-Small.median_with_onward_hops.beyond_first_account_share | pct }} | {{ tracer_evaluation_LI-Small.median_with_onward_hops.beyond_first_account_share | pct }} |
| Where the money moved: median precision (share of followed tainted money that moved through laundering transfers) | {{ tracer_evaluation_HI-Small.median_with_onward_hops.precision_usd | pct }} | {{ tracer_evaluation_LI-Small.median_with_onward_hops.precision_usd | pct }} |

**Reading.** In most simulated disputes the receiving account did not move the money within
72 hours, so there is nothing to trace and the money is still where it arrived. Where it did
move, the median dispute had almost all of its value beyond the first account: a return limited to
the first account, as in the original MED, would have reached little of it, which is the gap MED
2.0's tracing is meant to close. The tracer's allocation rule (tainted money leaves first, oldest
first) is deliberately pessimistic for recovery, and it shows: its precision against AMLworld's
labels is low, because it attributes tainted money to ordinary outflows that the simulator's own
accounting does not. The recoverable figure is an upper bound by construction (balances are not
observable), so it is not reported as a recovery rate. Known-answer and property tests check the
tracer's arithmetic (`tests/tracing`); these figures describe its usefulness on this data.

## 13. Investigation copilot

The copilot drafts a case file for an alerted account; an analyst approves, edits or rejects
it. Every claim in a draft must cite the transfers it relies on, and a deterministic fact checker
(`muletrace.validation.fact_checker`) rejects any draft with an unknown transfer, an amount,
date or account that does not match the evidence, an unknown typology, action or policy, a
recommendation to release funds, or an e-mail address or phone number. Rejected drafts never reach
the analyst. Design and limits: ADR-011.

The gold set is {{ copilot_eval_template_HI-Small.metrics.cases }} cases built from AMLworld's patterns file
(`evals/gold_cases/README.md`): 15 laundering attempts per typology, seen from the receiving
account, and 30 accounts that never received laundered money.

**What has been measured so far: the deterministic template baseline.** It writes the case file
with rules and no model, reads only the structure of the flows (never the free-text
descriptions), and is the bar the language-model copilots must clear.

| Template baseline, HI-Small gold set | Value |
|---|---:|
| Drafts delivered to the analyst | {{ copilot_eval_template_HI-Small.metrics.drafts_delivered }} of {{ copilot_eval_template_HI-Small.metrics.cases }} |
| Unsupported claims reaching the analyst | {{ copilot_eval_template_HI-Small.metrics.unsupported_claims_reaching_analyst }} |
| Claims citing at least one transfer | {{ copilot_eval_template_HI-Small.metrics.citation_coverage | pct }} |
| Recommended action accepted by the ground truth | {{ copilot_eval_template_HI-Small.metrics.action_agreement | pct }} |
| Typology matches the patterns file (attempts only) | {{ copilot_eval_template_HI-Small.metrics.typology_accuracy | pct }} |
| Attempt transfers cited in the draft | {{ copilot_eval_template_HI-Small.metrics.relevant_transaction_recall | pct }} |
| Complete drafts (summary, three or more claims, a policy reference) | {{ copilot_eval_template_HI-Small.metrics.completeness | pct }} |

**Is the checker strict enough?** Each delivered draft was perturbed five ways and checked again.
Rejection rates: invented transaction {{ copilot_eval_template_HI-Small.checker_strictness.invented_transaction.rejection_rate | pct }},
wrong amount {{ copilot_eval_template_HI-Small.checker_strictness.wrong_amount.rejection_rate | pct }},
wrong date {{ copilot_eval_template_HI-Small.checker_strictness.wrong_date.rejection_rate | pct }},
contact details in the summary {{ copilot_eval_template_HI-Small.checker_strictness.pii_in_summary.rejection_rate | pct }},
recommendation to release funds {{ copilot_eval_template_HI-Small.checker_strictness.release_recommended.rejection_rate | pct }}.

**Prompt injection.** Four attacks are planted in every transfer description of
{{ copilot_eval_template_HI-Small.adversarial.close_the_case.cases }} attempt cases (close the case, release the funds,
cite an invented transaction, copy contact details). None reached the analyst from the template
baseline, which is expected: it never reads descriptions. The suite exists for the language-model
copilots, which do.

**Reading.** The template proves the plumbing and sets the bar, not the ceiling. Its action
agreement is high because every attempt case contains ACH transfers, so the template holds all of
them; its disagreements are negative accounts that also have ACH activity, which it holds too. Its
typology accuracy is low because flow shape inside one account's window
rarely identifies AMLworld's typologies (a stack hop and a cycle hop look the same from one
account). Typology and transaction recall are where a model that reads the whole evidence should
improve.

**Not measured yet.** The single-call and multi-agent copilots on Amazon Bedrock (Nova Lite), their
cost, latency and token use, and the LLM judge. Bedrock was not available to this project when the
evaluation was run; the harness, the release gate (`configs/eval_thresholds.yaml`) and the
workflow (`.github/workflows/evals.yml`) are in place and run them as soon as model access is
configured. Judge results will only be reported next to their agreement with human labels
(`evals/judge_calibration/README.md`), which do not exist yet. No number for these is given here
because none has been measured.

## 14. Limitations of this evaluation

- Three hold-out days and ten days of data in total: nothing here describes behaviour over weeks.
- One random seed per model; the bootstrap covers sampling of accounts, not training randomness.
- Labels are perfect apart from the modelled delay; real labels are partial and biased.
- Hyper-parameters were chosen on the first fold only, which protects the hold-out but may leave
  later folds slightly under-tuned.
- The copilot evaluation covers one dataset (HI-Small) and, so far, only the template baseline.
