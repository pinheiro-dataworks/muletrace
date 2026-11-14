# Audit — week 5: operations, documentation and release

Date: 2026-11-14. Scope: everything merged for tag `v1.0.0`.

## 1. Gate results

Local run of every gate CI runs, on the merged branch: ruff (lint and format), mypy `--strict`
on `src/`, pytest with coverage, xenon, vulture, deptry, bandit, pip-audit and the authorship
scan all pass; the CDK app (seven stacks) synthesises with no unsuppressed cdk-nag error. Test
count and coverage are in the release commit message. Every commit of the week was checked out
on its own and its tests and lint run, so the history bisects.

## 2. What this week measured

| Measure | Result | Where |
|---|---|---|
| Drift, hold-out days against the last training day | score PSI at most 0.0196; account age drifts by construction | `docs/eval_report.md`, section 14 |
| Drift job, local run | 10.3 s, 1,313 MiB peak | `muletrace monitor drift` log |
| Demo build, 12 cases | 62 s, 5.5 GiB peak (scores three full snapshots) | `muletrace demo build` log |
| Pix-layer bundle | 14 files, 55 MB | `muletrace data export-pix-layer` |
| Stored feature vector size | median 932 bytes, maximum 1,046 bytes (2,000 accounts) | `docs/cost.md` |

Cloud cost this week: US$0. Prices in `docs/cost.md` come from the AWS Price List offer files,
with their publication dates.

## 3. Findings fixed before the release

- **Alarm and budget topics.** CloudWatch alarms and AWS Budgets cannot publish to an SNS topic
  encrypted with the AWS-managed key, which the existing alerts topic uses (AWS documentation).
  Wiring the drift alarms and the kill switch to it would have failed silently. They use their
  own topics; ADR-012 records why.
- **A CI action that no longer resolved.** The container workflow referenced
  `aquasecurity/trivy-action@0.28.0`, a tag that is no longer published. Every action is now
  pinned to a commit SHA and Trivy to its latest release.
- **Unverified package downloads.** Container requirements were exported without hashes. They now
  carry SHA-256 hashes, so pip refuses any archive that differs from the lock file. This path is
  exercised by the container workflow on push; Docker was not available locally.
- **`make all` stopped before the released model.** It now trains it and refreshes every report,
  which is the acceptance criterion.
- **The account-age artefact.** The drift check showed account age moving by 24 hours a day: it
  is measured from the first transaction in the data, not from account opening. It is the
  fourth most important feature, so this is a real limitation of the model, now stated in the
  model card, the evaluation report and the README, and the feature is excluded from alarms.
- **The demo's first draft showed only the saturated top of the queue**, where the calibrated
  probability ties at 1.0 and every account was a mule. Cases are now ranked by raw score and
  sampled across the whole alert list, so false positives appear in proportion.
- Smaller fixes: the template summary's grammar; a stray "null" in the demo; a heading that
  described a 0.2% score as "high"; a line over the length limit; two commits reordered so each
  passes its own tests.

## 4. Final checklist (build guide, section 9)

| Item | Status |
|---|---|
| Everything in English | Done |
| Only the owner as author; hook and CI check active | Done (`.githooks/commit-msg`, CI `authorship` job) |
| Data licence verified, saved and explained | Done (`data/LICENSES`, data card) |
| Leakage and label-delay tests passing | Done (property tests, delay sweep) |
| Baseline beaten with intervals, or honestly reported | Done (paired bootstrap intervals) |
| Copilot hallucination rate measured before and after the checker | **Partly**: measured for the template baseline; the language-model copilots need Bedrock access |
| Quality gates green; five weekly audits written | Done |
| Performance and cost measured, not estimated | **Partly**: everything local is measured; deployed figures are marked derived or not measured |
| Deploy and destroy both work from a clean clone | **Not verified**: needs the AWS account |
| Every public number traceable to `eval_report.md` | Done: the README, model card and dataset card render from the same generated files, and a test fails if any of them drifts |
| No claim from section 7 anywhere | Done (scanned before the release) |

## 5. Owner actions

These need credentials or a person, and nothing in the repository pretends they are done:

1. Push `main` and the tags; enable GitHub Pages (Settings → Pages → GitHub Actions).
2. AWS account setup, CDK bootstrap and the OIDC roles (`docs/runbook.md`); first deployment;
   measure deployed latency, cold start and cost per 1,000 scores; test the kill switch on
   purpose; tear down and check Cost Explorer two days later.
3. Enable Nova Lite and Nova Micro in Bedrock; run the copilot evaluation; label at least 30
   delivered case files and calibrate the judge.
4. Publish the Pix-layer bundle (`artifacts/publish/pix-layer`) on Hugging Face or Kaggle, and
   mirror the case explorer on a Hugging Face Space.
5. Record the 2–3 minute walkthrough video.
6. Create the GitHub release for `v1.0.0` with `artifacts/models/HI-Small/` attached.
7. Decide between archiving and the lean-live option (build guide, section 8).
