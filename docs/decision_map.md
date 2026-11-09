# Decision map

MuleTrace is built backwards from the decisions it changes. Each row links a problem to the
decision it informs, the action the analyst takes, the evidence MuleTrace produces and how the
impact is measured in this project. Impact is always measured on synthetic data.

| Problem | Decision | Action | Evidence MuleTrace provides | How impact is measured |
|---|---|---|---|---|
| Mule accounts receive and forward fraud proceeds before any dispute arrives | Which receiving accounts to review today, within a fixed analyst budget | Review the top-ranked accounts; place a precautionary hold or add to monitoring | Daily calibrated risk score per account with reason codes | Recall and simulated value detected at 20 alerts per 10,000 accounts, versus the rules baseline, with bootstrap intervals |
| When a dispute arrives, the first account is often already empty | Which onward accounts to notify and how much to ask each to block | Notify the next-hop institutions; prioritise branches with the largest recoverable balance | Hop-by-hop fund-flow trace with the recoverable balance estimated at each node | Known-answer tests on small graphs; conservation invariants; share of the disputed amount located after N hops |
| Analysts spend most of a case rebuilding evidence from raw transactions | Whether the evidence supports holding, monitoring or closing the case | Approve or reject the drafted case file and the recommended action | Draft case file in which every claim cites a transaction ID, checked by deterministic code | Unsupported-claim rate before and after the checker, citation coverage, typology accuracy, cost and latency per case |
| Rules decay and models drift as behaviour changes | Whether the score can still be trusted | Retrain, roll back or keep the current model | Weekly drift report (PSI and KS) on top features and the score distribution | Alarm thresholds and a documented retraining and rollback path |
| A demo or a bug can run up cloud costs | Whether to keep the system running | Let it run, or trip the kill switch | Budget alerts, anomaly detection and a kill-switch function | Measured build cost and cost per 1,000 scores and per copilot case |

## The analyst's day, end to end

1. The batch job builds the daily snapshot and scores every active receiving account.
2. The queue shows the top accounts within the budget, each with its reason codes.
3. For an account under review, or for a transfer just disputed, the tracer rebuilds where the
   money went and how much is still recoverable at each hop.
4. The copilot drafts the case file from the score, the reason codes, the trace and the policy
   library. The fact checker rejects any draft with a claim that does not match the data.
5. The analyst approves, edits or rejects the draft and the recommended action. MuleTrace never
   acts on its own.
