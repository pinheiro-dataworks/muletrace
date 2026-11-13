# Audit — week 3: production path on AWS

Date: 2026-11-13. Scope: everything merged for tag `v0.2.0`.

## 1. Gate results

Local run of every gate CI runs, on the merged branch: ruff (lint and format), mypy `--strict`
on `src/`, pytest with coverage, xenon, vulture, deptry, bandit, pip-audit and the authorship
scan all pass. Test count and coverage are in the release commit message. The new `infra` CI job
synthesises all five stacks and fails on any unsuppressed cdk-nag error; locally it passes.

## 2. Coverage and complexity

Cloud entry points that only wrap a library call (`*_handler` functions, the SageMaker
container's `main`) are excluded from coverage with a comment; everything they call is tested,
including an end-to-end run of the daily workflow with fake S3 and DynamoDB. The CLI was split
into one module per command group when it passed 300 lines, as planned in the week-1 audit.

## 3. Performance and cost

| Measure | Result | Budget |
|---|---|---|
| In-process scoring latency, p99 | 7.2 ms | warm Lambda p99 under 250 ms: **not yet measured**, needs a deployment |
| Model artefact | 1.5 MB, loads in 44 ms | none |
| Lambda image size | not measured locally (Docker unavailable); recorded by the CI container job | under 300 MB |
| Tracer evaluation, 70 traces | 8.7 s | none |

Cloud cost this week: US$0. Nothing was deployed: the AWS account setup is an owner action
(see `docs/runbook.md`).

## 4. Leakage and correctness review

| Risk | Control | Test |
|---|---|---|
| Batch/online skew | Features computed once in batch; lossless Decimal encoding; NaN for missing | Property test on the round trip; parity test vector by vector and score by score |
| Serving a model that differs from the evaluated one | `train_final_model` is the backtest's last fold; SageMaker runs the same function | End-to-end test trains through the SageMaker entry point |
| Tracer using money from before the dispute | Only transfers strictly after the disputed one are candidates | Known-answer test; property test on random graphs |
| Tracer creating money | Conservation by construction | Property test: recoverable plus left equals disputed |
| Promotion Lambda failing on the plain runtime | Dependency-free artefact names | Test that importing it loads no LightGBM, NumPy, Polars or pydantic |

## 5. Code I would not want to defend yet, and the fix

- **The promotion Lambda imported LightGBM** through the artefact module, which would have
  failed on its first approval. Found while writing the infrastructure, fixed, and now guarded by
  a test that imports it in a clean interpreter.
- **The tracer's allocation rule has low precision** against AMLworld's labels. Kept on purpose
  as the pessimistic choice (ADR-010); a pro-rata rule is the next experiment.
- **cdk-nag is pinned to 2.x.** Version 3 changed its suppression API; pinning keeps the checks
  stable. Revisit with the next CDK upgrade.
- **The promotion Lambda uses Python 3.14** while cdk-nag asks for 3.15; the suppression says why.
- **Deployed performance is unmeasured.** Every latency and cost figure so far is local and
  labelled as such.

## 6. Decisions and debts

Decisions: [ADR-009](../adr/009-serving-and-parity.md) serving and parity,
[ADR-010](../adr/010-tracer-allocation-rule.md) tracer allocation rule.

Debts: deployed latency, cold start, memory tuning and cost per 1,000 scores (need a
deployment); image size (CI); the daily schedule is disabled by design.

Open items carried over: AWS account setup and budgets (owner action); pushing the reviewed
history to GitHub.
