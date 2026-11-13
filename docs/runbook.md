# Runbook

How to stand MuleTrace up in an AWS account, operate it and tear it down. Everything here needs
the account owner's credentials; nothing in this repository has been deployed by CI on its own.

## 1. One-time account setup (owner, about two hours)

1. **Secure the root user** with MFA, then stop using it. Create an administrator in IAM Identity
   Center with MFA for console work.
2. **Region**: us-east-1 for everything.
3. **Bedrock model access**: enable the models the copilot uses (week 4), and only those.
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
- **Roll back a model**: re-approve the previous model package version.
- **Measure deployed performance**: record cold start, warm p50 and p99, and cost per 1,000 scores
  in `docs/performance.md` after the first deployment, and choose the Lambda memory size with a
  short benchmark at 512, 1,024 and 1,769 MB.

## 4. Tear down

```bash
make teardown        # or the deploy workflow with action: destroy
```

The data bucket empties itself on deletion. Two days later, check Cost Explorer for any
remaining spend, and delete the CDK bootstrap stack and the OIDC role if the project is archived.
