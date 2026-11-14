# ADR-006: Target definition and validation design

- Status: Accepted
- Date: 2026-11-09

## Context

The score must be judged the way it would be used: once a day, on accounts not yet known to be
mules, with labels that arrive late. AMLworld's primary period is only ten days (1–10 September
2022), followed by a short tail that is mostly laundering. A random split, or any split that lets
a training label depend on information from after the training date, would overstate results.

## Decision

- **Target.** At as-of time *t*, an account is positive if it is *confirmed* as a mule in
  `(t, t + 48 h]`. A mule is a receiving account with at least one laundering inflow
  (self-transfers excluded); it is confirmed 24 hours after its first illicit inflow. Both values
  are assumptions (A3 and A4) and live in `configs/labels.yaml`.
- **Population.** Accounts that received a transfer in the seven days before *t* and are not
  already confirmed at *t*.
- **Point in time.** Features use only rows with `timestamp < t`; neighbour labels use only
  confirmations at or before *t*. Property tests enforce both.
- **Snapshots.** Daily at 00:00 from 2 to 9 September. The last as-of time is the last one whose
  horizon ends inside the primary period, so the tail never decides a label window alone.
- **Hold-out.** 7, 8 and 9 September. The rules baseline and every model are scored on exactly
  these snapshots.
- **Training labels respect delay.** A model tested at *t* trains only on snapshots *s* whose
  labels are known by *t*: `labels_at(..., known_by=t)`, which in practice means `s + 48 h ≤ t`.
- **Pix-layer fields are not model features.** The model sees AMLworld behaviour only, so its
  results do not depend on choices made in the simulator. The rules baseline may use the Pix key
  age, because that is what a real rule would look at; the simulator makes it label-independent.

## Consequences

- Each test snapshot has at most five earlier snapshots with known labels, so training sets are
  small in time and models must be regularised accordingly.
- Results are reported per snapshot and pooled, with bootstrap intervals, because three test days
  are few and the weekday pattern differs.
- The design cannot say anything about drift over weeks or months.
