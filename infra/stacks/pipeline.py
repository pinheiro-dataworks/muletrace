"""Daily scoring: two batch Lambdas, the Step Functions workflow and its schedule."""

from __future__ import annotations

import json
from typing import Any

from aws_cdk import Duration, Size, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_sns as sns
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

from infra.stacks.common import REPO_ROOT, log_group, suppress
from muletrace.pipelines.step_functions import daily_scoring_definition

BATCH_MEMORY_MB = 6144


class PipelineStack(Stack):
    """BuildSnapshot → ScoreAndPublish, scheduled daily and disabled until enabled on purpose."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        bucket: s3.IBucket,
        feature_table: dynamodb.ITableV2,
        alerts_topic: sns.ITopic,
        **kwargs: Any,  # noqa: ANN401 - forwarded to cdk.Stack
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        image = ecr_assets.DockerImageAsset(
            self,
            "BatchImage",
            directory=str(REPO_ROOT),
            file="docker/batch.Dockerfile",
            platform=ecr_assets.Platform.LINUX_ARM64,
        )
        environment = {
            "DATA_BUCKET": bucket.bucket_name,
            "FEATURE_TABLE": feature_table.table_name,
            "MODEL_URI": f"s3://{bucket.bucket_name}/models/approved/current",
        }
        build = self._function("BuildSnapshot", image, environment, "build_snapshot_handler")
        score = self._function("ScoreAndPublish", image, environment, "score_and_publish_handler")
        bucket.grant_read(build, "processed/*")
        bucket.grant_write(build, "snapshots/*")
        bucket.grant_read(score, "snapshots/*")
        bucket.grant_read(score, "models/approved/*")
        bucket.grant_write(score, "scores/*")
        feature_table.grant_write_data(score)

        definition = daily_scoring_definition(
            build.function_arn, score.function_arn, alerts_topic.topic_arn
        )
        self.state_machine = sfn.StateMachine(
            self,
            "DailyScoring",
            definition_body=sfn.DefinitionBody.from_string(json.dumps(definition)),
            timeout=Duration.hours(1),
            tracing_enabled=True,
            logs=sfn.LogOptions(
                destination=log_group(self, "DailyScoringLogs"), level=sfn.LogLevel.ALL
            ),
        )
        build.grant_invoke(self.state_machine)
        score.grant_invoke(self.state_machine)
        alerts_topic.grant_publish(self.state_machine)
        self._schedule()
        self._suppressions()

    def _function(
        self,
        name: str,
        image: ecr_assets.DockerImageAsset,
        environment: dict[str, str],
        handler: str,
    ) -> lambda_.DockerImageFunction:
        return lambda_.DockerImageFunction(
            self,
            name,
            code=lambda_.DockerImageCode.from_ecr(
                image.repository,
                tag_or_digest=image.image_tag,
                cmd=[f"muletrace.pipelines.daily.{handler}"],
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=BATCH_MEMORY_MB,
            ephemeral_storage_size=Size.gibibytes(4),
            timeout=Duration.minutes(15),
            reserved_concurrent_executions=1,
            environment=environment,
            log_group=log_group(self, f"{name}Logs"),
        )

    def _schedule(self) -> None:
        role = iam.Role(
            self,
            "SchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        self.state_machine.grant_start_execution(role)
        scheduler.CfnSchedule(
            self,
            "DailySchedule",
            description="Daily scoring run. Disabled by default: AMLworld has fixed dates.",
            schedule_expression="cron(0 6 * * ? *)",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            state="DISABLED",
            target=scheduler.CfnSchedule.TargetProperty(
                arn=self.state_machine.state_machine_arn,
                role_arn=role.role_arn,
                input=json.dumps({"dataset": "HI-Small", "as_of": "2022-09-09"}),
            ),
        )

    def _suppressions(self) -> None:
        suppress(
            self,
            {
                "AwsSolutions-IAM4": "Batch Lambdas use the AWS-managed basic execution role, "
                "which only writes their own logs.",
                "AwsSolutions-IAM5": "Wildcards are scoped to bucket prefixes and to the two "
                "function versions the workflow invokes.",
            },
        )
