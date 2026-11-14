# Copilot gold cases

`HI-Small.jsonl` holds the 150 cases the copilot is evaluated on: 15 laundering attempts for each
of the eight AMLworld typologies (seen from the receiving account that takes most of the
attempt's transfers) and 30 accounts that never received laundered money. One JSON object per
line: the case evidence, the expected typology, the actions an analyst could accept and the IDs
of the transfers that belong to the attempt.

| Property | Value |
| --- | --- |
| Built by | `muletrace copilot gold --dataset HI-Small` (defaults: 15 per typology, 30 negatives, seed 20261113) |
| Transfers | 2,414 in total, 1 to 30 per case |
| Free-text descriptions | 752 transfers carry one |
| Ground truth | AMLworld `HI-Small_Patterns.txt` (typology, member transfers); expected action `hold` for attempts, `close` or `monitor` for negatives |

## Provenance and licence

The amounts, timestamps, account identifiers and payment formats are derived from the IBM
AMLworld HI-Small files, published under the Community Data License Agreement – Sharing,
Version 1.0 ([`data/LICENSES/CDLA-Sharing-1.0.txt`](../../data/LICENSES/CDLA-Sharing-1.0.txt)).
This file is shared under the same licence. AMLworld is synthetic: no case describes a real
person or institution.

The free-text descriptions are not part of AMLworld. They come from the Pix-layer simulator
(`muletrace.data.pix_layer_simulator`) and are synthetic as well.

Rebuild the file after any change to the data preparation, the simulator or the gold-case rules,
and review the diff before committing it: the evaluation numbers in
[`docs/eval_report.md`](../../docs/eval_report.md) are only comparable on the same gold set.
