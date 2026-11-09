# ADR-002: Region and services — us-east-1, pay-per-use only

- Status: Accepted
- Date: 2026-11-08

## Context

The cloud budget is a hard US$15 for the whole build, with an automatic deny at US$20. AWS has
no native hard spending cap, and billing data lags by hours, so cost has to be controlled by
design: nothing may bill by the hour while idle.

Two AWS services that would otherwise be natural choices are closed to new customers:

- **Amazon Fraud Detector** stopped accepting new customers on 7 November 2025; existing
  customers can keep using it (AWS documentation, *Amazon Fraud Detector availability change*).
- **Amazon SageMaker Model Monitor** and **Amazon SageMaker Clarify** close to new customers
  effective 30 July 2026 (AWS documentation, *availability change* pages for each service).

## Decision

- All resources in **us-east-1**, where model availability on Bedrock is broadest.
- Storage: S3 (Parquet, zstd). Online features: DynamoDB on demand.
- Training: SageMaker Training Jobs on Spot capacity with a maximum runtime; experiments stay on
  the laptop.
- Serving: Lambda container images on arm64 behind an HTTP API with throttling.
- Orchestration: EventBridge Scheduler → Step Functions → Lambda.
- Event replay: script → SQS → Lambda (no Kinesis shards).
- Drift monitoring built in-house: a weekly Lambda computing PSI and KS with NumPy and SciPy,
  CloudWatch custom metrics and SNS alerts.
- Cost guards: AWS Budgets with a budget action, Cost Anomaly Detection and a kill-switch Lambda.
- Infrastructure as code: AWS CDK in Python, checked with cdk-nag.
- Not used: always-on SageMaker real-time endpoints, NAT gateways, load balancers and any other
  resource that bills per hour while idle.

## Consequences

- The idle cost of the deployed system is close to zero, and `cdk destroy` brings it to zero.
- Lambda cold starts become part of the latency budget and have to be measured.
- Drift monitoring is small and owned by the project, which is more code to test but also easier
  to explain than a managed service that new accounts cannot enable.
- MuleTrace is positioned as an open alternative after Amazon Fraud Detector closed to new
  customers, not as a replacement for any commercial product.
