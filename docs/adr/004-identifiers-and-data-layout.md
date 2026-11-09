# ADR-004: Identifiers and data layout

- Status: Accepted
- Date: 2026-11-08

## Context

The copilot must cite transaction IDs, and the fact checker must verify them. AMLworld has no
transaction identifier, repeats the column name `Account` for sender and receiver, writes bank
codes as zero-padded strings in the transactions file (`"010"`) and as integers in the accounts
file (`10`), and contains a few byte-identical transactions (9 in HI-Small, 8 in LI-Small).

## Decision

- `tx_id` is the zero-based data-row number in the source CSV. Because `data/MANIFEST.yaml`
  pins each file by SHA-256, the identifier is reproducible and maps to exactly one source line.
  Identical rows keep distinct identifiers.
- An account is identified by `(bank_id, account_number)` with `bank_id` as an integer. Its
  `account_key` is `"<bank_id>:<account_number>"`, and its compact `account_id` (`UInt32`) is the
  rank of the key in lexicographic order, so the mapping does not depend on file order.
- Each table is one zstd-compressed Parquet file, sorted by `(timestamp, tx_id)`. At this size
  (137 MB for HI-Small and 189 MB for LI-Small on disk, all core tables), Parquet row-group
  statistics already give predicate pushdown on time, and date partitioning would only add
  small files.
- Amounts stay `Float64` (values reach 1e12 and the checker compares cents); currencies,
  payment formats, entity types and typologies are enums; identifiers are `UInt32`.

## Consequences

- Any number the copilot cites can be checked with a single lookup by `tx_id`.
- Re-downloading a different Kaggle version would silently change row numbers. The manifest
  check runs before preparation precisely to make that loud.
