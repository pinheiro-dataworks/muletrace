# Cost

What MuleTrace has cost so far, what it costs per unit of work, and what it costs when archived.
Every figure is labelled **measured**, **derived** (arithmetic on published prices, no deployed
measurement) or **not measured yet**. Prices are on-demand, us-east-1, from the AWS Price List
API offer files; their publication dates are given so they can be checked again.

## 1. Build cost to date

| Item | Cost | Status |
|---|---:|---|
| AWS (all services) | US$0 | **Measured**: nothing has been deployed and Bedrock has not been called. The account setup is an owner action (`docs/runbook.md`). |
| Kaggle, BCB open data, GitHub Actions | US$0 | **Measured**: public data and the free tier of a public repository |
| Laptop compute | not priced | Times and peak memory are in [`docs/performance.md`](performance.md) |

The cost guards are in place before anything is deployed: a US$15 monthly budget with alerts at
50%, 80% (forecast) and 100%, the kill switch at 100%, a deny policy on the deployment role at
US$20, and daily cost-anomaly e-mails (`MuleTrace-CostGuards`, `MuleTrace-Monitoring`).

## 2. Prices used

| Service | Unit | Price (USD) | Offer file publication |
|---|---|---:|---|
| Lambda, arm64 | per request | 0.0000002 | 2026-11-11T22:30:04Z |
| Lambda, arm64 | per GB-second (first tier) | 0.0000133334 | 2026-11-11T22:30:04Z |
| API Gateway HTTP API | per request (first 300 million) | 0.000001 | 2026-11-12T21:59:20Z |
| DynamoDB on demand | per read request unit | 0.000000125 | 2026-11-11T15:36:12Z |
| DynamoDB on demand | per write request unit | 0.000000625 | 2026-11-11T15:36:12Z |
| Bedrock, Amazon Nova Lite | per 1,000 input / output tokens | 0.00006 / 0.00024 | 2026-11-11T01:30:37Z |
| Bedrock, Amazon Nova Micro | per 1,000 input / output tokens | 0.000035 / 0.00014 | 2026-11-11T01:30:37Z |
| Bedrock Guardrails, content filters (includes prompt attacks) | per 1,000 text units | 0.15 | 2026-11-11T01:30:37Z |
| Bedrock Guardrails, denied topics | per 1,000 text units | 0.15 | 2026-11-11T01:30:37Z |

A guardrail text unit is up to 1,000 characters, counted once per policy type that evaluates it.
The offer file also lists sensitive-information units at US$0 and at US$0.10 per 1,000 text
units; which line applies to the copilot's e-mail and phone filters will be read from the first
bill.

## 3. Cost per 1,000 scores

One score is one HTTP API request, one Lambda invocation (1,024 MB, arm64) and one DynamoDB
read. A stored feature vector is about 1 KB (median 932 bytes, maximum 1,046 bytes over 2,000
HI-Small accounts, **measured** with the serving code), so each eventually consistent read uses
half a read request unit.

| Part | Per 1,000 scores (USD) | Status |
|---|---:|---|
| HTTP API requests | 0.001 | **Derived** |
| Lambda requests | 0.0002 | **Derived** |
| DynamoDB reads (500 read request units) | 0.0000625 | **Derived** |
| Lambda compute | 0.0000133 per billed millisecond of a warm invocation | **Derived formula**; the deployed duration is **not measured yet** |

So the fixed part is about US$0.0013 per 1,000 scores, plus US$0.0000133 for every billed
millisecond. The in-process scoring time is 5.6 ms at the median (`docs/performance.md`), but a
deployed invocation also includes the DynamoDB round trip and Lambda's own overhead, so the
billed duration will be higher; it is reported after the first deployment, together with cold
starts. The Lambda free tier is not counted.

## 4. Cost per copilot case

| Measure | Value | Status |
|---|---:|---|
| Template baseline | US$0 | **Measured**: no model call |
| Single-call and multi-agent copilots | — | **Not measured yet**: Bedrock was not available to this project |
| Upper bound on model cost, multi-agent copilot on Nova Lite | US$0.0048 | **Derived**: a case stops at 20,000 tokens (`configs/copilot.yaml`); the bound assumes all of them were output tokens, the dearer kind |
| Release gate | US$0.01 per case on average | `configs/eval_thresholds.yaml` |

Guardrail charges come on top of the model cost and scale with the characters each policy
evaluates (section 2). They are measured with the first Bedrock evaluation run.

## 5. Archived cost

| State | Expected | Status |
|---|---:|---|
| After `make teardown` | US$0 per month | **Not verified yet**: Cost Explorer must be checked two days after the first teardown. Every stack deletes its resources, including the data bucket's objects; what remains by design is the CDK bootstrap stack (its staging bucket and container repository hold the deployment assets) and the GitHub OIDC role, which the runbook removes when the project is archived. |
| GitHub repository, release, static demo | US$0 | Public repository and GitHub Pages |
