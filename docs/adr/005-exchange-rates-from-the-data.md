# ADR-005: Exchange rates inferred from the data

- Status: Accepted
- Date: 2026-11-08

## Context

AMLworld amounts are in fifteen currencies, including Bitcoin. Features need one unit of
account and the Pix layer needs Brazilian reals. Importing market rates would mix a real-world
reference with a synthetic world whose simulator uses its own rates.

## Decision

Rates are read from the data: for every transfer paid in one currency and received in another,
`amount_received / amount_paid` is the simulator's rate. The table stores, per currency, the
median units per US dollar, the number of observations and the relative interquartile range.
All amounts are converted to US dollars for features; BRL amounts in the Pix layer use the
inferred `Brazil Real` rate.

In HI-Small every fiat currency has a relative IQR below 1e-5 (the rates are effectively
constant). Bitcoin is the exception at about 5%, which is acceptable for feature scaling but is
noted in the data card.

## Consequences

- No external data source, no licence question and no time-alignment problem.
- The rate table is a static property of the synthetic world, so estimating it from all rows
  does not leak information across time.
- Conversions are only as faithful as the simulator; they say nothing about real exchange rates.
