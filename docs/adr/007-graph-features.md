# ADR-007: Graph features — simple aggregates, PageRank and neighbour labels

- Status: Accepted
- Date: 2026-11-09

## Context

Mule accounts sit in networks. The question is how much graph machinery the score needs.
Learned embeddings (for example GraphSAGE) cost training time and are hard to keep point-in-time
correct; the build plan says to start with aggregates and PageRank and add embeddings only if an
ablation shows a gap.

## Decision

On the past-to-future graph at as-of time *t* (one directed edge per distinct sender–receiver
pair seen strictly before *t*, self-transfers excluded), compute with sparse matrices:

- in- and out-degree, and PageRank (scaled so the average account has rank 1);
- one-hop aggregates of the senders: mean out-degree and mean PageRank;
- neighbour labels, using **only confirmations at or before *t***: confirmed senders, confirmed
  receivers, and senders that themselves have confirmed senders.

Connected components of the trailing week were implemented and **dropped**: measured on the
7 September HI-Small snapshot, one weakly connected component contains 343,397 accounts and the
median scored account belongs to it, so component size and its mule count carry no information.
`distinct_inflow_currencies` was dropped for the same reason (it is 1 for every account: each
AMLworld account receives in one currency).

## Consequences

- The whole HI-Small feature build, graph features included, takes 28.2 seconds for 8 snapshots
  on a laptop (peak memory 2,495 MiB; see `docs/performance.md`).
- Neighbour labels make the graph features depend on the confirmation delay. The cache key
  includes the label configuration, and the label-delay sweep rebuilds them for every delay.
- Community structure is not represented. If the ablation shows that graph features matter, the
  next step is a community algorithm on the recent graph, then embeddings.
