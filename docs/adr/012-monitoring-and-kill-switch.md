# ADR-012: In-house drift monitoring and a cost kill switch

- Status: Accepted
- Date: 2026-11-14

## Context

The score needs a signal that its inputs or outputs have moved away from what it was trained
on, and the project needs a way to stop spending money quickly. Amazon SageMaker Model Monitor
is no longer open to new customers (SageMaker developer guide, "Amazon SageMaker Model Monitor
availability change"), and it is built around SageMaker endpoints, which this project does not
use. AWS has no hard spending cap, and billing data lags by hours.

## Decision

1. **Drift is computed in a small Lambda** from what the daily workflow already writes: the
   scored snapshot of a day against the last training snapshot. PSI over reference deciles and
   the two-sample KS statistic, in NumPy, on the score and the five most important features. At
   most ten CloudWatch custom metrics, two alarms (score PSI and the largest alerting feature
   PSI) on a monitoring topic. Thresholds are labelled conventions in `configs/monitoring.yaml`.
2. **Features that drift by construction are reported, not alarmed.** Account age grows 24 hours
   a day because it is measured from the start of the data; alarming on it would page someone
   every week for nothing.
3. **The kill switch throttles, it does not delete.** When the monthly budget is reached, AWS
   Budgets publishes to a topic and a Lambda sets every MuleTrace function's reserved concurrency
   to zero and disables the schedules. Restoring is one direct invocation. Deleting is left to
   `make teardown`, a deliberate human action.
4. **The alarm and kill-switch topics are not encrypted with the AWS-managed SNS key**, because
   CloudWatch alarms and AWS Budgets cannot publish to such a topic; they carry notices only.

## Consequences

- No managed service to depend on, and the whole check runs locally too
  (`muletrace monitor drift`), which is how the account-age artefact was found.
- PSI and KS describe distributions, not performance. Performance needs labels, which arrive with
  the confirmation delay; a label-based monitor (recall at the budget on confirmed cases) is the
  next step once there is real label history.
- Throttling stops compute but not storage, which costs cents for this data. A budget breach
  caused by something outside MuleTrace's functions is not stopped by the kill switch; the
  US$20 deny policy and the anomaly e-mails remain.
- Revisit thresholds after real alarm history exists.
