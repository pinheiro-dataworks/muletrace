"""Cost kill switch: stop everything that can spend money on its own, in one call.

AWS has no hard spending cap and billing data lags by hours, so when the monthly budget is
reached AWS Budgets publishes to an SNS topic and this function:

1. sets the reserved concurrency of every listed Lambda function to zero, so the scoring API,
   the replay consumer, the copilot and the batch steps stop executing at once;
2. disables every listed EventBridge Scheduler schedule.

Nothing is deleted, so the system can be restored without a redeployment: invoking the function
directly with ``{"action": "restore"}`` puts each function's normal concurrency back. Schedules
stay disabled; they are disabled by default and are enabled by a person on purpose.

Configuration comes from the environment: ``KILL_FUNCTIONS`` maps function names to their normal
reserved concurrency (JSON), ``KILL_SCHEDULES`` lists ``[group, name]`` pairs (JSON). Clients are
injectable so the logic is tested locally.
"""

from __future__ import annotations

import json
import os
from typing import Any, Final

# Fields of a GetSchedule response that UpdateSchedule accepts; everything else is read-only.
_SCHEDULE_FIELDS: Final = (
    "Name",
    "GroupName",
    "ScheduleExpression",
    "ScheduleExpressionTimezone",
    "StartDate",
    "EndDate",
    "Description",
    "KmsKeyArn",
    "Target",
    "FlexibleTimeWindow",
    "ActionAfterCompletion",
)


def kill(
    lambda_client: Any,  # noqa: ANN401 - boto3 clients
    scheduler: Any,  # noqa: ANN401
    functions: dict[str, int],
    schedules: list[tuple[str, str]],
) -> dict[str, Any]:
    """Throttle every function to zero and disable every schedule."""
    for name in functions:
        lambda_client.put_function_concurrency(FunctionName=name, ReservedConcurrentExecutions=0)
    disabled = []
    for group, name in schedules:
        current = scheduler.get_schedule(GroupName=group, Name=name)
        if current.get("State") != "DISABLED":
            update = {key: current[key] for key in _SCHEDULE_FIELDS if key in current}
            scheduler.update_schedule(**update, State="DISABLED")
            disabled.append(name)
    return {"action": "kill", "throttled": sorted(functions), "schedules_disabled": disabled}


def restore(lambda_client: Any, functions: dict[str, int]) -> dict[str, Any]:  # noqa: ANN401
    """Put back each function's normal reserved concurrency."""
    for name, concurrency in functions.items():
        lambda_client.put_function_concurrency(
            FunctionName=name, ReservedConcurrentExecutions=concurrency
        )
    return {"action": "restore", "restored": dict(sorted(functions.items()))}


def run(
    event: dict[str, Any],
    lambda_client: Any,  # noqa: ANN401
    scheduler: Any,  # noqa: ANN401
    environment: dict[str, str],
) -> dict[str, Any]:
    """Restore on an explicit ``{"action": "restore"}``; any other event (SNS) kills."""
    functions = {str(k): int(v) for k, v in json.loads(environment["KILL_FUNCTIONS"]).items()}
    if event.get("action") == "restore":
        return restore(lambda_client, functions)
    schedules = [(str(g), str(n)) for g, n in json.loads(environment.get("KILL_SCHEDULES", "[]"))]
    return kill(lambda_client, scheduler, functions, schedules)


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:  # pragma: no cover
    """Lambda entry point."""
    import boto3  # noqa: PLC0415

    return run(event, boto3.client("lambda"), boto3.client("scheduler"), dict(os.environ))
