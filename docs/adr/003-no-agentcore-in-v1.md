# ADR-003: No Bedrock AgentCore in v1

- Status: Accepted
- Date: 2026-11-08

## Context

The copilot coordinates three small agents (evidence, typology, report) that call a handful of
deterministic tools. Amazon Bedrock AgentCore offers a managed runtime, memory and gateway for
agents. The project has to show that the copilot's quality, safety and cost are *measured*,
which requires every step to be reproducible in a test harness.

## Decision

The orchestrator is plain Python running in a Lambda function. Agents call the Bedrock Converse
API with tool use directly. AgentCore is not used in v1.

## Consequences

- The same orchestrator runs in unit tests (with a scripted model client), in the evaluation
  harness and in Lambda, so evaluation results describe the code that is deployed.
- There is no managed agent memory or session store; each case is stateless, which suits a
  case-file workflow.
- Revisit if the copilot needs long-running sessions, shared memory across cases or many more
  tools than the current handful.
