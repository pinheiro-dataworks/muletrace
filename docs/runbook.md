# Runbook

How to stand MuleTrace up in an AWS account, operate it and tear it down. Everything here needs
the account owner's credentials; nothing in this repository has been deployed by CI on its own.

## 1. One-time account setup (owner, about two hours)

1. **Secure the root user** with MFA, then stop using it. Create an administrator in IAM Identity
   Center with MFA for console work.
2. **Region**: us-east-1 for everything.
3. **Bedrock model access**: enable Amazon Nova Lite and Nova Micro (the copilot's models), and
   only those.
4. **CDK bootstrap**, once, from CloudShell: `npx aws-cdk@2 bootstrap aws://<account-id>/us-east-1`.
5. **GitHub OIDC role**: deploy `infra/bootstrap/github-oidc-role.yaml` (the command is in its
   header). Set the two subject parameters to the exact `sub` claims GitHub issues for this
   repository's `dev` and `production` environments; check the claim format in GitHub's OIDC
   documentation first. Pull requests and forks must never match.
6. **GitHub environments**: create `dev` and `production`; require a reviewer on `production`.
   Set the repository variables `AWS_DEPLOY_ROLE_ARN` (output of step 5) and `ALERT_EMAIL`.
7. **Budgets and anomaly detection** are part of the `MuleTrace-CostGuards` stack (US$15 alerts,
   US$20 deny action, daily anomaly e-mails). Confirm the SNS and budget e-mails after the first
   deployment.

## 2. Deploy

From GitHub: run the `deploy` workflow with `action: deploy`. It deploys to `dev` from `main`,
then waits for approval on `production`. From a laptop with an AWS profile:

```bash
make synth                                  # stack assertions, cdk-nag and cdk synth
make deploy ALERT_EMAIL=you@example.com     # all stacks
```

Then load data and a first model:

```bash
aws s3 sync data/processed/HI-Small s3://<data-bucket>/processed/HI-Small --exclude "pix_layer/*"
uv run python scripts/start_training_job.py --bucket <data-bucket> \
    --role-arn <sagemaker-role-arn> --image-uri <training-image-uri>
```

Register the finished job's `model.tar.gz` with
`muletrace.pipelines.sagemaker_training.model_package_request` and `register_model`, then approve
the package in SageMaker Studio or with `aws sagemaker update-model-package`. Approval triggers the
promotion Lambda, which publishes the artefact under `models/approved/<version>/` and points the
scorer at it.

## 3. Operate

- **Daily scoring**: the schedule is created **disabled** because AMLworld has fixed dates. Start
  an execution by hand with `{"dataset": "HI-Small", "as_of": "2022-09-09"}`, or enable the
  schedule after changing its input.
- **Score an account**: `GET /score/{account_id}?as_of=YYYY-MM-DD` on the HTTP API, signed with
  SigV4 (the route uses IAM authorisation).
- **Replay transfers**: `uv run python scripts/replay_transfers.py --queue-url <url> --start ...
  --end ...`; alerts appear in the replay consumer's logs.
- **Roll back a model**: in the model registry, set the bad version to `Rejected`, then move the
  previous version to `PendingManualApproval` and back to `Approved`. The approval event
  re-runs the promotion Lambda, which points the scorer at that version's artefact (every
  promoted version stays under `models/approved/<version>/`). The next cold start serves it.
- **Draft a case file**: invoke the `MuleTrace-Agents` copilot Lambda with a `CaseEvidence` JSON
  document. The answer says whether the draft was delivered and, if not, which fact-checker rules
  rejected it. Only an analyst acts on a case.
- **Measure deployed performance**: record cold start, warm p50 and p99, and cost per 1,000 scores
  in `docs/performance.md` after the first deployment, and choose the Lambda memory size with a
  short benchmark at 512, 1,024 and 1,769 MB.

## 4. Monitor drift, retrain, roll back

The `MuleTrace-Monitoring` stack runs a drift check that compares a scored day with the
reference day in `configs/monitoring.yaml` (PSI and KS on the score and five features). Its
weekly schedule is created **disabled**, like the daily workflow; invoke the drift Lambda by hand
with `{"current_day": "2022-09-09"}` after a daily run. The full report is written to
`monitoring/drift/<dataset>/<day>.json`; two CloudWatch alarms (`ScorePSI` and `MaxFeaturePSI`
above 0.25) notify the monitoring topic. Run the same check locally with
`uv run muletrace monitor drift --days 2022-09-07 2022-09-08 2022-09-09`.

When an alarm fires:

1. Read the stored report: which column moved, and by how much. Features listed as
   `report_only` (account age, which grows with the calendar by construction) never alarm.
2. Check the input first. A drift caused by a broken upstream job (empty snapshot, missing
   accounts, a changed currency table) is fixed upstream, not by retraining.
3. If the population really changed, **retrain**: run the training job on the latest labelled
   snapshots (`scripts/start_training_job.py`), register the package, and compare its
   validation metrics with the current model's before approving. Approval promotes it.
4. If the new model performs worse in its first days, **roll back** as described in section 3.

## 5. Kill switch

When the monthly budget (US$15) is reached, AWS Budgets publishes to the kill-switch topic and
the kill-switch Lambda sets the reserved concurrency of every MuleTrace function to zero and
disables both schedules. Nothing is deleted. At US$20 the budget action also denies the
deployment role any new billable resource.

- **Test it on purpose** once after the first deployment: publish any message to the
  `KillSwitch` topic (`aws sns publish --topic-arn <arn> --message test`), then check that the
  scorer answers with a throttling error and that both schedules are disabled.
- **Restore**: invoke the kill-switch Lambda directly with `{"action": "restore"}`; it puts every
  function's normal concurrency back. Schedules stay disabled until a person enables them.

## 6. Tear down

```bash
make teardown        # or the deploy workflow with action: destroy
```

The data bucket empties itself on deletion. Two days later, check Cost Explorer for any
remaining spend, and delete the CDK bootstrap stack and the OIDC role if the project is archived.
