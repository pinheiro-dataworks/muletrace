"""Amazon States Language definition of the daily scoring workflow.

``BuildSnapshot`` computes the point-in-time features for the as-of date and writes them to S3;
``ScoreAndPublish`` writes the feature vectors to DynamoDB for the scoring Lambda and the scores
to S3 for the drift job. Both steps retry transient Lambda errors with backoff, and any failure
publishes to the alerts topic before the execution fails. The definition is a plain dictionary
so it can be reviewed and tested without AWS; the CDK stack serialises it.
"""

from __future__ import annotations

from typing import Any, Final

_TRANSIENT_ERRORS: Final = [
    "Lambda.ServiceException",
    "Lambda.AWSLambdaException",
    "Lambda.SdkClientException",
    "Lambda.TooManyRequestsException",
]


def _lambda_task(function_arn: str, next_state: str | None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {"FunctionName": function_arn, "Payload.$": "$"},
        "ResultSelector": {"result.$": "$.Payload"},
        "ResultPath": "$.last_step",
        "Retry": [
            {
                "ErrorEquals": _TRANSIENT_ERRORS,
                "IntervalSeconds": 5,
                "MaxAttempts": 3,
                "BackoffRate": 2.0,
            }
        ],
        "Catch": [
            {"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "NotifyFailure"}
        ],
    }
    if next_state is None:
        state["End"] = True
    else:
        state["Next"] = next_state
    return state


def daily_scoring_definition(
    build_function_arn: str, score_function_arn: str, alerts_topic_arn: str
) -> dict[str, Any]:
    """The workflow; its input is ``{"dataset": "...", "as_of": "YYYY-MM-DD"}``."""
    return {
        "Comment": "MuleTrace daily scoring: build the snapshot, then score and publish.",
        "StartAt": "BuildSnapshot",
        "TimeoutSeconds": 3600,
        "States": {
            "BuildSnapshot": _lambda_task(build_function_arn, "ScoreAndPublish"),
            "ScoreAndPublish": _lambda_task(score_function_arn, None),
            "NotifyFailure": {
                "Type": "Task",
                "Resource": "arn:aws:states:::sns:publish",
                "Parameters": {
                    "TopicArn": alerts_topic_arn,
                    "Subject": "MuleTrace daily scoring failed",
                    "Message.$": "States.JsonToString($)",
                },
                "Next": "Failed",
            },
            "Failed": {"Type": "Fail", "Error": "DailyScoringFailed"},
        },
    }
