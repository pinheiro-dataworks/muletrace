# Architecture decision records

One decision per file, numbered in the order they were taken. A record is never edited to
change its decision; a later record supersedes it instead.

| ADR | Title | Status |
|---|---|---|
| [001](001-scope.md) | Scope: one user, one workflow, small datasets | Accepted |
| [002](002-region-and-services.md) | Region and services: us-east-1, pay-per-use only | Accepted |
| [003](003-no-agentcore-in-v1.md) | No Bedrock AgentCore in v1 | Accepted |
| [004](004-identifiers-and-data-layout.md) | Identifiers and data layout | Accepted |
| [005](005-exchange-rates-from-the-data.md) | Exchange rates inferred from the data | Accepted |
| [006](006-target-and-validation-design.md) | Target definition and validation design | Accepted |

Template: *Context* (what forces the decision), *Decision* (what we do), *Consequences*
(what gets easier, what gets harder, what we would revisit).
