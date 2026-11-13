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
  1,000 replicates; the same resampling weights are
  applied to every model, so differences have their own intervals.

Prevalence on the hold-out snapshots:

| Snapshot | HI-Small scored | HI-Small positives | per 10,000 | LI-Small scored | LI-Small positives | per 10,000 |
|---|---:|---:|---:|---:|---:|---:|
| 7 Sep | 276,396 | 705 | 25.51 | 378,429 | 624 | 16.49 |
| 8 Sep | 277,651 | 716 | 25.79 | 380,315 | 640 | 16.83 |
| 9 Sep | 250,313 | 731 | 29.20 | 342,924 | 625 | 18.23 |

## 2. Headline: the model ladder at the analyst budget

HI-Small hold-out, 20 alerts per 10,000 scored accounts:

| Model | Recall (95% CI) | Precision | Average precision (95% CI) | Value share |
|---|---:|---:|---:|---:|
| Rules, hand-set thresholds | 1.4% (1.0 to 2.0%) | 1.9% | 0.007 (0.006 to 0.009) | 2.8% |
| Rules, thresholds tuned on training snapshots | 1.5% (1.1 to 2.1%) | 2.1% | 0.007 (0.006 to 0.008) | 1.7% |
| LightGBM, behaviour features | 15.7% (14.2 to 17.1%) | 21.0% | 0.126 (0.112 to 0.143) | 12.6% |
| **LightGBM, behaviour + graph** | **18.5%** (17.0 to 20.0%) | 24.7% | **0.159** (0.144 to 0.176) | 3.1% |

Paired differences (HI-Small hold-out, 20 alerts per 10,000):

| Comparison | Recall difference (95% CI) | Average-precision difference (95% CI) |
|---|---:|---:|
| Graph model minus tuned rules | 16.9% (15.3 to 18.5%) | 0.152 (0.138 to 0.169) |
| Graph model minus behaviour-only model (graph ablation) | 2.8% (1.7 to 4.0%) | 0.033 (0.023 to 0.042) |
| Tuned rules minus hand-set rules | 0.1% (-0.4 to 0.7%) | 0.000 (-0.001 to 0.001) |

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
| Rules, hand-set | 2.0% (1.3 to 2.6%) | 0.005 (0.004 to 0.006) |
| Rules, tuned | 1.4% (0.9 to 1.9%) | 0.005 (0.004 to 0.006) |
| LightGBM, behaviour | 10.5% (9.2 to 11.8%) | 0.038 (0.032 to 0.046) |
| LightGBM, behaviour + graph | 11.9% (10.3 to 13.3%) | 0.064 (0.054 to 0.077) |

Graph ablation on LI-Small: recall difference
1.3%
(0.0 to 2.7%),
average-precision difference
0.027
(0.019 to 0.034).
Tuned minus hand-set rules:
-0.6%
(-1.0 to -0.2%).

**Reading.** With fewer mules everything is harder, but the ordering holds. The graph gain in
recall at the budget is not distinguishable from zero on LI-Small (its interval touches zero),
while its gain in average precision is. Tuning the rules on training snapshots made them *worse*
on the hold-out: the thresholds chosen on a handful of training days did not transfer, a small
example of why a rules engine tuned by hand needs the same temporal validation as a model.

## 4. Stability across folds (HI-Small)

Recall at 20 alerts per 10,000, per test snapshot:

| Model | 6 Sep | 7 Sep | 8 Sep | 9 Sep |
|---|---:|---:|---:|---:|
| Rules, tuned | 1.9% | 0.7% | 1.4% | 2.5% |
| LightGBM, behaviour | 10.8% | 11.8% | 18.6% | 16.6% |
| LightGBM, behaviour + graph | 11.9% | 14.6% | 20.0% | 20.7% |

The model improves as more training snapshots become available (the 6 September fold trains on
two days only) and the graph model is ahead of the behaviour-only model on every fold.

## 5. Recall across budgets (HI-Small hold-out)

| Alerts per 10,000 | 5 | 10 | 20 | 50 | 100 |
|---|---:|---:|---:|---:|---:|
| Rules, tuned | 0.7% | 0.9% | 1.5% | 2.5% | 4.3% |
| LightGBM, behaviour + graph | 11.2% | 14.4% | 18.5% | 25.8% | 34.6% |
| Precision, graph model | 59.9% | 38.6% | 24.7% | 13.8% | 9.3% |

## 6. Where the model wins and where it fails (HI-Small hold-out, graph model)

Recall at 20 alerts per 10,000 among positives:

| Slice | Positives | Recall |
|---|---:|---:|
| Already active at the as-of time | 1,224 | 32.2% |
| Not yet active at the as-of time | 928 | 0.3% |
| Inside a recorded typology: stack | 324 | 30.3% |
| Scatter-gather | 182 | 33.5% |
| Gather-scatter | 151 | 30.5% |
| Cycle | 139 | 32.4% |
| Fan-out | 114 | 29.8% |
| Bipartite | 106 | 17.9% |
| Random | 89 | 25.8% |
| Fan-in | 14 | 28.6% |
| No recorded pattern | 1,033 | 6.5% |

**Reading.** The score is a detector of **active, not-yet-confirmed** mules, not a predictor of
future recruitment: an account whose first illicit inflow happens after the as-of time has nothing
in its past to give it away. Mules inside a recorded laundering pattern are found far more often
than those whose laundering follows no pattern. Fan-in has very few positives, so its rate is
noisy.

**Value detected is small.** At the headline budget, alerted accounts receive
3.1% of the
simulated illicit inflow that arrives during the horizon. Most of that money reaches accounts
that were not yet active when scored, which is exactly the slice the model misses. This is the
honest limit of an account-level daily score, and the reason the fund-flow tracer exists.

## 7. Calibration (HI-Small hold-out, graph model)

| Brier score | Value |
|---|---:|
| Raw scores | 0.0026 |
| After isotonic calibration | 0.0024 |
| Constant equal to the prevalence | 0.0027 |

Mean calibrated probability 0.27%
against an observed rate of 0.27%.
The isotonic map saturates at 1.0 for the highest scores (every validation account in that range
was a mule), which over-states certainty at the very top; see the week-2 audit.

## 8. Expected cost (HI-Small hold-out, review units)

A false positive costs one review; a missed mule costs C_FN reviews (assumption A2). Costs are
summed over the three hold-out snapshots.

| C_FN | No alerts | Rules (tuned) at budget | Graph model at budget | Graph model, best budget | Graph model, threshold policy |
|---:|---:|---:|---:|---:|---:|
| 10 | 21,520 | 22,962 | 18,760 | 18,654 | 19,037 |
| 50 | 107,600 | 108,442 | 88,960 | 76,988 | 80,286 |
| 100 | 215,200 | 215,292 | 176,710 | 142,632 | 147,399 |
| 500 | 1,076,000 | 1,070,092 | 878,710 | 656,297 | 501,351 |

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
| 0 h | 1,757 | 0.0% | 0.5% (0.2 to 0.8%) | 0.4% (0.2 to 0.7%) | 0.003 |
| 12 h | 1,977 | 33.8% | 11.9% (10.6 to 13.4%) | 9.4% (8.1 to 10.8%) | 0.079 |
| 24 h (default) | 2,152 | 56.9% | 18.5% (17.0 to 20.0%) | 15.7% (14.2 to 17.1%) | 0.159 |
| 48 h | 2,372 | 100.0% | 22.5% (21.0 to 23.9%) | 18.6% (17.2 to 19.9%) | 0.232 |
| 72 h | 2,211 | 100.0% | 19.3% (17.9 to 20.8%) | 16.5% (15.1 to 17.9%) | 0.193 |

**Reading.** The result runs against the naive expectation that later labels make the problem
harder. With no delay, every positive becomes a mule *after* the as-of time, nothing in its past
gives it away, and recall at the budget collapses to
0.5%. As the delay grows,
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
| HI-Small | 47.62% | 59.2% | 39.8% | 28.70% | 56.77% | 62.86% |
| LI-Small | 15.83% | 26.7% | 11.2% | 7.90% | 16.45% | 20.83% |

Paper figures: Altman et al., arXiv:2306.16424, Table 2 (means over several runs; MuleTrace
reports a single run, so its numbers carry no interval).

**Reading.** The data handling reproduces the paper's ordering: results land above the paper's
plain GIN and below its graph-feature-preprocessed gradient boosting, on both datasets. The gap to
GFP + LightGBM is the price of using simple window aggregates instead of a dedicated graph-pattern
feature generator. These are modest numbers, reported as they are.

## 11. What drives the score

Mean absolute SHAP contribution on the HI-Small hold-out (graph model), top five:
inflow_usd_24h,
sender_mean_out_degree,
ach_inflow_share,
account_age_hours and
inflow_usd_168h.
The full list is in `docs/generated/backtest_HI-Small.yaml`; reason codes for the top of the
queue are shown in `notebooks/02_error_analysis.ipynb`.

## 12. Fund-flow tracer

Every accepted MED-style dispute in the Pix layer is traced with the parameters in
`configs/tracer.yaml` (maximum 5 hops, a
72-hour hop window, transfers of at
least US$10), and scored against
AMLworld's own laundering labels, which follow laundered money through later transfers.

| | HI-Small | LI-Small |
|---|---:|---:|
| Accepted disputes traced | 30 | 40 |
| Disputes where the money moved on within the window | 13 | 17 |
| Deepest hop reached | 5 | 4 |
| Where the money moved: median share of the disputed amount located beyond the first account | 100.0% | 99.9% |
| Where the money moved: median precision (share of followed tainted money that moved through laundering transfers) | 23.0% | 0.0% |

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

## 13. Limitations of this evaluation

- Three hold-out days and ten days of data in total: nothing here describes behaviour over weeks.
- One random seed per model; the bootstrap covers sampling of accounts, not training randomness.
- Labels are perfect apart from the modelled delay; real labels are partial and biased.
- Hyper-parameters were chosen on the first fold only, which protects the hold-out but may leave
  later folds slightly under-tuned.
- The copilot evaluation (week 4) is reported separately.
