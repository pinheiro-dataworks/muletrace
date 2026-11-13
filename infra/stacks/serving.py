"""Serving: the scoring Lambda behind an IAM-authorised HTTP API, and the replay queue."""

from __future__ import annotations

from typing import Any

from aws_cdk import Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as sources
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from infra.stacks.common import REPO_ROOT, log_group, suppress

SCORER_MEMORY_MB = 1024
SCORER_CONCURRENCY = 5


class ServingStack(Stack):
    """The online path: score on demand, and check replayed transfers."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        bucket: s3.IBucket,
        feature_table: dynamodb.ITableV2,
        **kwargs: Any,  # noqa: ANN401 - forwarded to cdk.Stack
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        image = ecr_assets.DockerImageAsset(
            self,
            "ScorerImage",
            directory=str(REPO_ROOT),
            file="docker/lambda.Dockerfile",
            platform=ecr_assets.Platform.LINUX_ARM64,
        )
        environment = {
            "FEATURE_TABLE": feature_table.table_name,
            "MODEL_URI": f"s3://{bucket.bucket_name}/models/approved/current",
            "DATASET": "HI-Small",
            "PROBABILITY_CAP": "0.99",
        }
        self.scorer = self._function("Scorer", image, environment, None)
        self.replay_consumer = self._function(
            "ReplayConsumer",
            image,
            {**environment, "ALERT_THRESHOLD": "0.5"},
            ["muletrace.serving.replay_consumer.handler"],
        )
        for function in (self.scorer, self.replay_consumer):
            feature_table.grant_read_data(function)
            bucket.grant_read(function, "models/approved/*")

        self.api = self._api()
        self.replay_queue = self._replay_queue()
        self._suppressions()

    def _function(
        self,
        name: str,
        image: ecr_assets.DockerImageAsset,
        environment: dict[str, str],
        command: list[str] | None,
    ) -> lambda_.DockerImageFunction:
        return lambda_.DockerImageFunction(
            self,
            name,
            code=lambda_.DockerImageCode.from_ecr(
                image.repository, tag_or_digest=image.image_tag, cmd=command
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=SCORER_MEMORY_MB,
            timeout=Duration.seconds(15),
            reserved_concurrent_executions=SCORER_CONCURRENCY,
            environment=environment,
            log_group=log_group(self, f"{name}Logs"),
            tracing=lambda_.Tracing.ACTIVE,
        )

    def _api(self) -> apigw.HttpApi:
        api = apigw.HttpApi(
            self,
            "ScoreApi",
            create_default_stage=False,
            default_authorizer=authorizers.HttpIamAuthorizer(),
        )
        api.add_routes(
            path="/score/{account_id}",
            methods=[apigw.HttpMethod.GET],
            integration=integrations.HttpLambdaIntegration("ScoreIntegration", self.scorer),
        )
        stage = apigw.HttpStage(
            self,
            "ScoreStage",
            http_api=api,
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=5, burst_limit=10),
        )
        access_logs = log_group(self, "ScoreApiAccessLogs")
        cfn_stage = stage.node.default_child
        cfn_stage.access_log_settings = apigw.CfnStage.AccessLogSettingsProperty(  # type: ignore[union-attr]
            destination_arn=access_logs.log_group_arn,
            format='{"requestId":"$context.requestId","routeKey":"$context.routeKey",'
            '"status":"$context.status","latencyMs":"$context.responseLatency"}',
        )
        return api

    def _replay_queue(self) -> sqs.Queue:
        dead_letters = sqs.Queue(
            self,
            "ReplayDeadLetters",
            enforce_ssl=True,
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            retention_period=Duration.days(4),
        )
        queue = sqs.Queue(
            self,
            "ReplayQueue",
            enforce_ssl=True,
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            visibility_timeout=Duration.seconds(90),
            dead_letter_queue=sqs.DeadLetterQueue(queue=dead_letters, max_receive_count=3),
        )
        self.replay_consumer.add_event_source(
            sources.SqsEventSource(queue, batch_size=10, report_batch_item_failures=True)
        )
        return queue

    def _suppressions(self) -> None:
        suppress(
            self,
            {
                "AwsSolutions-IAM4": "Lambda functions use the AWS-managed basic execution and "
                "X-Ray policies, which grant only log and trace writes.",
                "AwsSolutions-IAM5": "Wildcards are limited to the models/approved/ prefix of the "
                "data bucket and to X-Ray, which has no resource-level permissions.",
                "AwsSolutions-SQS3": "The dead-letter queue is itself the DLQ of the replay queue.",
            },
        )
