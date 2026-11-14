# Audit — week 4: investigation copilot and its evaluation

Date: 2026-11-14. Scope: everything merged for tag `v0.3.0`.

## 1. Gate results

Local run of every gate CI runs, on the merged branch: ruff (lint and format), mypy `--strict`
on `src/`, pytest with coverage, xenon, vulture, deptry, bandit, pip-audit and the authorship
scan all pass; the CDK app (now six stacks) synthesises with no unsuppressed cdk-nag error. Test
count and coverage are in the release commit message. Each of the week's commits was checked
out on its own and its tests run, so the history bisects.

## 2. What was measured, and what was not

| Measure | Result |
|---|---|
| Template baseline on the 150-case gold set | gate passed; numbers in `docs/eval_report.md`, section 13 |
| Fact checker against five perturbations of every delivered draft | every perturbed draft rejected |
| Template evaluation run time | 0.5 s, peak memory 68 MiB, local |
| Single-call and multi-agent copilots on Bedrock | **not measured**: no Bedrock access in this environment |
| Copilot cost per case and latency | **not measured**, same reason; budgets are in `configs/eval_thresholds.yaml` |
| LLM judge | **not reported**: no human labels yet (`evals/judge_calibration/README.md`) |

Cloud cost this week: US$0. Model prices in `configs/copilot.yaml` come from the AWS Price List
API offer file for Amazon Bedrock in us-east-1, with its publication date recorded next to them.

## 3. Correctness and safety review

| Risk | Control | Test |
|---|---|---|
| A draft cites a transfer that does not exist | Checker rule `unknown_transaction`, also on IDs mentioned in the text | Unit tests; perturbation rate in every evaluation |
| A draft gets an amount, date or account wrong | Exact comparison with the cited transfers (amounts within one cent, or their sum) | Unit tests; perturbation rates |
| A model follows text planted in a description | Descriptions returned as `untrusted_customer_text`; checker rejects released funds and contact details; the analyst approves | Four attacks in the adversarial suite, counted per attack |
| The guardrail is assumed to cover tool results | It does not (Bedrock user guide); recorded in ADR-011 | Not testable without Bedrock; the adversarial suite measures the end result |
| The phone rule fires on amounts | Pattern requires space or dash separators and rejects digits after `.` or `,` | Unit tests with amounts, dates and real-looking numbers |
| The deployed copilot differs from the evaluated one | The CDK stack reads model, price and budget from `configs/copilot.yaml` | Infra test checks the model ID in the Lambda environment |
| A runaway conversation burns tokens | Per-case token budget and a cap on tool rounds | Unit tests on both limits |

## 4. Code I would not want to defend yet, and the fix

- **Eight functions in the copilot and evaluation code were complexity grade C or D** when first
  written (the checker, the metrics summary, the release gate, the judge calibration and the
  template heuristic). Split into small named helpers before merging; xenon passes at the
  project's thresholds.
- **A dependency audit found CVE-2026-126347 in tornado 6.6**, which arrives through Jupyter in
  the notebooks group. Upgraded to 6.6.1 in its own commit.
- **The template's typology accuracy is low.** Expected: one account's flow shape rarely
  identifies AMLworld's typology. It is a floor for the language-model copilots, not a target.
- **The evaluation covers HI-Small only.** LI-Small gold cases can be built with the same
  command; deferred until the Bedrock runs exist, so both datasets are compared on the same
  providers.

## 5. Decisions and debts

Decision: [ADR-011](../adr/011-copilot-grounding-and-guardrails.md) structured claims, the
deterministic checker as the gate, and what the guardrail can and cannot see.

Debts, all owner actions: enable Nova Lite and Nova Micro in the AWS account and run the Bedrock
evaluation (`.github/workflows/evals.yml` or `muletrace copilot eval --provider multi`); label at
least 30 delivered case files for judge calibration; deploy the agents stack and measure the
copilot's deployed latency and cost per case.
