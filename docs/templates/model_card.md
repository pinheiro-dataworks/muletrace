# Model card: MuleTrace receiving-account risk score

<!-- Rendered from docs/templates/model_card.md by `muletrace docs render`.
     Every number below is a placeholder resolved against docs/generated/*.yaml;
     a test fails if this file and its template drift apart. Do not edit numbers by hand. -->

| | |
|---|---|
| Model | LightGBM on point-in-time behaviour and graph features, isotonic calibration |
| Version | the artefact trained by `muletrace models train-final` for the tagged release |
| Owner | Renan Pinheiro |
| Training data | IBM AMLworld HI-Small (synthetic), snapshots 2 to 6 September 2022; validated on 7 September |
| Evaluation | [`docs/eval_report.md`](eval_report.md); design in [ADR-006](adr/006-target-and-validation-design.md) |
| Data | [`docs/data_card.md`](data_card.md) |

## Intended use

Rank receiving accounts once a day so that a fraud or AML analyst team reviews the riskiest
first, within a fixed budget of alerts (20 per 10,000 scored accounts by default). The score
answers one question: *is this account likely to be confirmed as a mule within the next 48
hours?* A person reviews every alert; the score never blocks, holds or reports an account on its
own. Reason codes (the largest SHAP contributions) come with every score so the reviewer sees why
the account ranks high.

## Out of scope

- Real customers or real Pix data. The model was trained and evaluated only on synthetic data;
  its numbers say nothing about performance on a real payment system.
- Automatic decisions: holding funds, closing accounts or filing reports without a person.
- Predicting who *will be* recruited as a mule. The score detects accounts that are already
  active (see the slices below).
- Transaction-level blocking at payment time. The score is computed daily per account; the
  external transaction-level check in the evaluation report is a comparison, not a use case.
- Use as evidence about a person. A score is a reason to look, not a finding.

## Metrics (hold-out: 7, 8 and 9 September 2022)

The figures come from the rolling-origin backtest. The released artefact is trained exactly like
its last fold (same features, hyper-parameters and label truncation), so they describe the model
that is deployed. At 20 alerts per 10,000 scored accounts, 95% intervals from a paired Poisson
bootstrap:

| Dataset | Recall (95% CI) | Precision | Average precision (95% CI) | Recall of tuned rules, same budget |
|---|---:|---:|---:|---:|
| HI-Small | {{ backtest_HI-Small.bootstrap.recall.lgbm_tabular_graph.estimate | pct }} ({{ backtest_HI-Small.bootstrap.recall.lgbm_tabular_graph.ci95 | ci }}) | {{ backtest_HI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=20].precision | pct }} | {{ backtest_HI-Small.bootstrap.average_precision.lgbm_tabular_graph.estimate | f3 }} ({{ backtest_HI-Small.bootstrap.average_precision.lgbm_tabular_graph.ci95 | ci3 }}) | {{ backtest_HI-Small.bootstrap.recall.rules_tuned.estimate | pct }} |
| LI-Small | {{ backtest_LI-Small.bootstrap.recall.lgbm_tabular_graph.estimate | pct }} ({{ backtest_LI-Small.bootstrap.recall.lgbm_tabular_graph.ci95 | ci }}) | {{ backtest_LI-Small.hold_out.lgbm_tabular_graph[alerts_per_10k=20].precision | pct }} | {{ backtest_LI-Small.bootstrap.average_precision.lgbm_tabular_graph.estimate | f3 }} ({{ backtest_LI-Small.bootstrap.average_precision.lgbm_tabular_graph.ci95 | ci3 }}) | {{ backtest_LI-Small.bootstrap.recall.rules_tuned.estimate | pct }} |

Calibration (HI-Small hold-out): Brier score
{{ backtest_HI-Small.calibration.lgbm_tabular_graph.brier_calibrated | f4 }} after isotonic
calibration, against {{ backtest_HI-Small.calibration.lgbm_tabular_graph.brier_constant_prevalence | f4 }}
for a constant equal to the prevalence. The isotonic map reaches 1.0 at the very top of the
score range, so displayed probabilities are capped at 0.99.

## Slices (HI-Small hold-out, recall at the headline budget)

| Slice | Positives | Recall |
|---|---:|---:|
| Already active at the as-of time | {{ backtest_HI-Small.slices_lgbm_tabular_graph.activity.already active at as-of.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.activity.already active at as-of.recall | pct }} |
| Not yet active at the as-of time | {{ backtest_HI-Small.slices_lgbm_tabular_graph.activity.not yet active.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.activity.not yet active.recall | pct }} |
| Inside a recorded laundering pattern: stack | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.STACK.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.STACK.recall | pct }} |
| No recorded pattern | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.no pattern.positives | int }} | {{ backtest_HI-Small.slices_lgbm_tabular_graph.typology.no pattern.recall | pct }} |

Every typology slice is in section 6 of the evaluation report.

## Who pays for an error

| Error | Who bears it | How the design limits it |
|---|---|---|
| False positive: a legitimate account is alerted | The analyst team (review time) and the customer (friction, possibly a temporary hold decided by a person) | A fixed alert budget; reason codes; a person decides every action |
| False negative: a mule is not alerted | The scam victim first, then the provider through reimbursement rules, regulatory exposure and reputation | Daily re-scoring; the fund-flow tracer follows disputed money beyond the first account |

Costs are modelled in review units in the [business case](business_case.md) (assumptions A1 and
A2), never in money.

## Monitoring

A drift job compares each scored day with the last training snapshot (6 September). On the
hold-out, the score's population stability index stayed at
{{ drift_HI-Small.days.2022-09-07.score.psi | f4 }},
{{ drift_HI-Small.days.2022-09-08.score.psi | f4 }} and
{{ drift_HI-Small.days.2022-09-09.score.psi | f4 }} (alert threshold
{{ drift_HI-Small.thresholds.psi_alert | f2 }}). Account age did not: its PSI was
{{ drift_HI-Small.days.2022-09-09.features.account_age_hours.psi | f2 }} by 9 September, because
it is measured from the first transaction *in the data* and every account ages 24 hours a day.
It is reported but excluded from alerting; the runbook describes the response to a real alarm,
retraining and rollback.

## Limitations

- **Synthetic data only.** AMLworld's laundering is generated by known rules; real mule
  behaviour is more varied and adapts to detection.
- **Ten days of data.** Nothing here describes behaviour over weeks or months, seasonality or
  the decay of a model after deployment.
- **Account age is left-censored.** It is measured from 1 September 2022, the first day of the
  data, not from account opening. It is the fourth most important feature, so part of what the
  model learned about "new accounts" is an artefact of the data window. A real deployment must
  use the account's opening date.
- **Labels are perfect apart from the modelled delay.** Real confirmations are partial and
  biased toward what earlier controls already caught.
- **No fairness assessment.** AMLworld has no attributes about people, so no group-level
  analysis is possible here; a real deployment needs one.
- **One seed per model.** The intervals cover resampling of accounts, not training randomness.
