"""Shared constructs and conventions for every MuleTrace stack."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_logs as logs
from cdk_nag import NagSuppressions
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_RETENTION = logs.RetentionDays.TWO_WEEKS


def log_group(scope: Construct, construct_id: str) -> logs.LogGroup:
    """A log group that expires after two weeks and is deleted with the stack."""
    return logs.LogGroup(
        scope, construct_id, retention=LOG_RETENTION, removal_policy=RemovalPolicy.DESTROY
    )


def suppress(stack: Stack, rules: dict[str, str], path: str | None = None) -> None:
    """Record a cdk-nag suppression with its justification, on a path or the whole stack."""
    suppressions = [{"id": rule, "reason": reason} for rule, reason in rules.items()]
    if path is None:
        NagSuppressions.add_stack_suppressions(stack, suppressions)
    else:
        NagSuppressions.add_resource_suppressions_by_path(stack, path, suppressions, True)
