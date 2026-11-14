# Judge calibration

The LLM judge (`muletrace.evals.judge`) answers four yes/no questions about a delivered case
file: `clear_summary`, `action_justified`, `no_speculation` and `analyst_ready`. A judge number
means nothing until it is compared with a person's answers to the same questions, so judge
results are not reported anywhere until this folder holds human labels.

## Status

**No human labels yet.** `labels.csv` contains only its header. Labelling is an owner action:
it needs Bedrock access to produce the case files to label.

## How to label

1. Run the copilot on the gold set (`muletrace copilot eval --provider multi`). Delivered case
   files are kept in `artifacts/copilot/multi_HI-Small.jsonl` (not committed). Pick at least
   30 of them, covering every typology and every recommended action.
2. For each case file and each criterion, add one row: `case_id,criterion,human_pass`, where
   `human_pass` is `true` or `false`. Leave it empty if you cannot decide; empty rows are ignored.
3. Label before looking at the judge's verdicts.
4. Set `judge_model` in `configs/copilot.yaml` to a model enabled in the account, run the judge
   and report its true-positive and true-negative rates (`muletrace.evals.judge.calibration`)
   next to every judge number.
