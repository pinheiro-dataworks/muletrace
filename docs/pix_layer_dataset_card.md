---
license: cdla-sharing-1.0
pretty_name: MuleTrace Pix layer for IBM AMLworld (synthetic)
language:
  - en
tags:
  - synthetic
  - anti-money-laundering
  - fraud-detection
  - instant-payments
  - pix
size_categories:
  - 1M<n<10M
---

# MuleTrace Pix layer for IBM AMLworld (synthetic)

<!-- Rendered from docs/templates/pix_layer_dataset_card.md by `muletrace docs render`.
     Numbers come from docs/generated/pix_layer_calibration.yaml. -->

**This dataset is entirely synthetic and derived from IBM AMLworld.** It adds a simulated
Brazilian instant-payment (Pix) layer to the HI-Small and LI-Small files of IBM's AMLworld
(Altman et al., *Realistic Synthetic Financial Transactions for Anti-Money Laundering Models*,
arXiv:2306.16424): instant-transfer re-labelling with amounts in reals, Pix keys, DICT-style
fraud markings, MED-style disputes and free-text transfer descriptions. No real person, account,
bank or transaction appears in it. It is shared under the Community Data License Agreement –
Sharing, Version 1.0, the licence of AMLworld itself.

It was built for [MuleTrace](https://github.com/pinheiro-dataworks/muletrace) by Renan Pinheiro
with simulator version 0.1.0 and seed
20,261,108. It is not affiliated with, endorsed by or
calibrated with any data from Banco Central do Brasil beyond the public aggregates listed below,
and it is not an official Pix or MED artefact.

## What changed relative to AMLworld

AMLworld's rows are never modified or re-published. The layer sits next to them and joins by
identifier:

- `tx_id` is the zero-based data-row number in AMLworld's `*_Trans.csv` file (Kaggle dataset
  `ealtman2019/ibm-transactions-for-anti-money-laundering-aml`). Download the original files to
  recover the full transactions; `MANIFEST.yaml` in the MuleTrace repository records the exact
  file checksums the identifiers refer to.
- `account_id` is the rank of `"<bank_id>:<account_number>"` in lexicographic order;
  `account_map.parquet` maps it back to AMLworld's bank and account columns.

## Files

Per dataset folder (`HI-Small/`, `LI-Small/`):

| File | Rows (HI-Small) | Rows (LI-Small) | Content |
|---|---:|---:|---|
| `pix_transfers.parquet` | 700,510 | 928,231 | ACH and Wire transfers between different accounts, re-labelled as instant transfers: amount in BRL, night-time flags, synthetic description |
| `pix_keys.parquet` | 515,088 | 705,907 | One synthetic key per account (opaque token; e-mail keys use `example.invalid`) and its registration time |
| `pix_dict_markings.parquet` | 3,984 | 3,303 | A DICT-style fraud marking for every confirmed mule, at confirmation time |
| `pix_disputes.parquet` | 328 | 437 | MED-style disputes with outcome (accepted or rejected) and scam scenario |
| `account_map.parquet` | | | `account_id`, `bank_id`, `account_number` |
| `calibration_report.yaml` | | | Targets and achieved values for this dataset |

`MANIFEST.yaml` lists the size and SHA-256 checksum of every file.

## Calibration to public figures

Only public aggregates from the Banco Central do Brasil open-data service were used (MED
statistics, October 2025 to September 2026; stock of Pix keys on 31 October 2026):

| Target | Public figure | HI-Small | LI-Small |
|---|---:|---:|---:|
| Accepted disputes per 100,000 instant transfers | 4.31 | 4.28 | 4.31 |
| Share of disputes rejected | 90.85% | 90.85% | 90.85% |
| Average accepted ticket (BRL, rounded) | 2,265 | 4,002,141 | 61,162 |

The ticket is deliberately not matched: amounts are AMLworld's own, converted to reals, so every
row still joins to its source. AMLworld's laundering transfers are far larger than Brazilian
scam transfers; **no amount in this dataset should be read as a Brazilian figure.** Key-type
shares match the public stock to within 0.15 percentage points (see `calibration_report.yaml`).
The night-time limit (R$ 1,000 per transfer between individuals, 20:00 to 06:00) follows the
default described in the BCB *Relatório de Gestão do Pix* (2023) and is recorded as a flag;
transfers are not blocked.

## Assumptions

Not sourced, chosen for this simulation: ACH and Wire are the formats re-labelled as instant
transfers; Individual and Sole Proprietorship accounts are treated as natural persons; key
registration times are uniform over the year before an account's first transfer; a mule is
confirmed 24 hours after its first illicit inflow; disputes are filed 1 to 72 hours after the
transfer; scam scenarios and descriptions are short English templates.

## Intended use and cautions

- Research and teaching on receiving-side fraud, fund-flow tracing and the evaluation of
  investigation copilots, including prompt-injection tests through the description field.
- **The layer encodes AMLworld's labels.** DICT markings exist only for confirmed mules and
  accepted disputes only on laundering transfers. Using them as model features leaks the label.
- Descriptions are templates, not natural customer language.
- Not for drawing conclusions about the real Pix system, its users or its fraud levels.

## Licence and attribution

Community Data License Agreement – Sharing, Version 1.0 (`LICENSE`). Derived from IBM AMLworld,
also CDLA-Sharing-1.0. When you share a modified version, keep this licence and say what you
changed. Code that produced the layer: Apache-2.0, in the MuleTrace repository.
