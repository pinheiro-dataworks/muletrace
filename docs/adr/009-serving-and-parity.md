# ADR-009: Serving — precomputed features, lossless encoding, capped probabilities

- Status: Accepted
- Date: 2026-11-09

## Context

The score is used once a day for the queue and on demand when an analyst opens an account. The
features need the full transfer graph, which a Lambda cannot rebuild per request within a
latency budget of 250 ms (p99, warm). Batch/online skew is the most common way a correct model
becomes wrong in production, and DynamoDB, the cheapest online store here, stores numbers as
decimals and has no NaN. The backtest also showed that isotonic calibration saturates at 1.0 for
the highest scores.

## Decision

- **Features are computed once, in batch,** by the same `build_snapshots` code the model was
  evaluated on, and written to DynamoDB. The Lambda only reads, decodes and scores.
- **Encoding is lossless and explicit**: floats are written as `Decimal(repr(x))`, which
  round-trips bit for bit; missing values are not written and are read back as NaN, which is how
  LightGBM treats missing values in the batch path. A property test checks the round trip and a
  parity test checks that batch and online produce the same vector and the same score.
- **The artefact loads with LightGBM and NumPy only.** Calibration is applied with
  `numpy.interp`; Polars, scikit-learn and pandera stay out of the image.
- **Displayed probabilities are capped** (default 0.99, `PROBABILITY_CAP`), and the response says
  when the cap applied. The raw score is returned too, so ranking is never affected.
- **The model loads once per container** (first request) and is reused while the container lives.

## Consequences

- Scores are as fresh as the last batch run (daily). An account that becomes active during the
  day is not re-scored until the next run; the event-replay path is where intraday scoring would
  start.
- The image needs the OpenMP runtime for LightGBM (`libgomp`), installed in the Dockerfile.
- Parity is guaranteed by tests, not by convention: changing the encoding or the feature order
  breaks a test before it breaks production.
