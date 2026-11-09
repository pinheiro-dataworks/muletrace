## Context

<!-- Why this change is needed. Link the issue, ADR or audit item. -->

## Change

<!-- What changed, in a few bullet points. -->

## Evidence

<!-- Test output, metrics, benchmark numbers or screenshots that show it works. -->

## Audit checklist

- [ ] `make check` passes locally (lint, mypy --strict, tests, coverage, complexity, dead code, deps, security)
- [ ] New or changed logic has tests; critical modules keep at least 95% coverage
- [ ] No look-ahead: features and labels only use information available at the as-of time
- [ ] Performance measured where it matters, numbers recorded in `docs/performance.md`
- [ ] Docs, data card or model card updated if behaviour or numbers changed
- [ ] Every published number is traceable to `docs/eval_report.md`
- [ ] No secrets, no raw AMLworld rows, no AI attribution lines
