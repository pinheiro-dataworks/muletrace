"""Monitoring and the cost kill switch.

* A weekly drift Lambda compares the latest scored snapshot with the reference day and puts the
  statistics in CloudWatch; two alarms (score PSI, largest alerting feature PSI) notify a
  monitoring topic. The schedule starts disabled, like the daily workflow: AMLworld's dates are
  fixed, so a person picks the day to check.
* A kill-switch Lambda, subscribed to its own topic, sets every MuleTrace function's reserved
  concurrency to zero and disables both schedules. The cost-guards stack makes AWS Budgets publish
  to that topic when the monthly budget is reached.

Both topics are left without server-side encryption on purpose: CloudWatch alarms and AWS Budgets
cannot publish to a topic encrypted with the AWS-managed SNS key, and a customer-managed key
would cost more per month than this project's archived target. They carry alarm and budget
notices only, never data.
"""

from __future__ import annotations

import json
from typing import Any

from aws_cdk import Duration, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as actions
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from constructs import Construct

from infra.stacks.common import REPO_ROOT, log_group, suppress
from muletrace.config import CONFIG_DIR, load_config
from muletrace.monitoring.drift import DriftConfig
from muletrace.monitoring.job import NAMESPACE

DRIFT_MEMORY_MB = 2048
# AMLworld's last hold-out snapshot; a person changes the input when checking another day.
DRIFT_INPUT_DAY = "2022-09-09"


class MonitoringStack(Stack):
    """Weekly drift check with alarms, and the kill switch."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        bucket: s3.IBucket,
        throttled: dict[str, tuple[lambda_.IFunction, int]],
        daily_schedule: scheduler.CfnSchedule,
        daily_schedule_role: iam.IRole,
        alert_email: str | None = None,
        **kwargs: Any,  # noqa: ANN401 - forwarded to cdk.Stack
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        config = load_config(DriftConfig, CONFIG_DIR / "monitoring.yaml")
        self.alarm_topic = self._topic("MonitoringAlarms", "MuleTrace monitoring alarms")
        if alert_email:
            self.alarm_topic.add_subscription(subscriptions.EmailSubscription(alert_email))

        self.drift = self._drift_function(bucket)
        weekly_role = iam.Role(
            self, "DriftSchedulerRole", assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com")
        )
        self.drift.grant_invoke(weekly_role)
        self.weekly_schedule = scheduler.CfnSchedule(
            self,
            "WeeklyDrift",
            description="Weekly drift check. Disabled by default: AMLworld has fixed dates.",
            schedule_expression="cron(0 7 ? * MON *)",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            state="DISABLED",
            target=scheduler.CfnSchedule.TargetProperty(
                arn=self.drift.function_arn,
                role_arn=weekly_role.role_arn,
                input=json.dumps({"current_day": DRIFT_INPUT_DAY}),
            ),
        )
        self._alarms(config)

        self.kill_switch_topic = self._topic("KillSwitch", "MuleTrace cost kill switch")
        self.kill_switch_topic.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal("budgets.amazonaws.com")],
                actions=["sns:Publish"],
                resources=[self.kill_switch_topic.topic_arn],
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            )
        )
        functions = {**throttled, "drift": (self.drift, 1)}
        schedules = [
            (daily_schedule, daily_schedule_role),
            (self.weekly_schedule, weekly_role),
        ]
        self._kill_switch(functions, schedules)
        self._suppressions()

    def _topic(self, construct_id: str, display_name: str) -> sns.Topic:
        return sns.Topic(self, construct_id, display_name=display_name, enforce_ssl=True)

    def _drift_function(self, bucket: s3.IBucket) -> lambda_.DockerImageFunction:
        image = ecr_assets.DockerImageAsset(
            self,
            "BatchImage",
            directory=str(REPO_ROOT),
            file="docker/batch.Dockerfile",
            platform=ecr_assets.Platform.LINUX_ARM64,
        )
        function = lambda_.DockerImageFunction(
            self,
            "DriftJob",
            code=lambda_.DockerImageCode.from_ecr(
                image.repository,
                tag_or_digest=image.image_tag,
                cmd=["muletrace.monitoring.job.handler"],
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=DRIFT_MEMORY_MB,
            timeout=Duration.minutes(5),
            reserved_concurrent_executions=1,
            environment={"DATA_BUCKET": bucket.bucket_name},
            log_group=log_group(self, "DriftJobLogs"),
        )
        bucket.grant_read(function, "snapshots/*")
        bucket.grant_read(function, "scores/*")
        bucket.grant_put(function, "monitoring/drift/*")
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": NAMESPACE}},
            )
        )
        return function

    def _alarms(self, config: DriftConfig) -> None:
        dimensions = {"Dataset": config.dataset}
        for metric_name, description in (
            ("ScorePSI", "The score distribution moved away from the reference day."),
            ("MaxFeaturePSI", "A monitored feature moved away from the reference day."),
        ):
            alarm = cloudwatch.Alarm(
                self,
                f"{metric_name}Alarm",
                alarm_description=f"{description} See docs/runbook.md, drift.",
                metric=cloudwatch.Metric(
                    namespace=NAMESPACE,
                    metric_name=metric_name,
                    dimensions_map=dimensions,
                    period=Duration.days(1),
                    statistic="Maximum",
                ),
                threshold=config.psi_alert,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            alarm.add_alarm_action(actions.SnsAction(self.alarm_topic))

    def _kill_switch(
        self,
        functions: dict[str, tuple[lambda_.IFunction, int]],
        schedules: list[tuple[scheduler.CfnSchedule, iam.IRole]],
    ) -> None:
        kill = lambda_.Function(
            self,
            "KillSwitchFunction",
            runtime=lambda_.Runtime.PYTHON_3_14,
            architecture=lambda_.Architecture.ARM_64,
            handler="muletrace.ops.kill_switch.handler",
            code=lambda_.Code.from_asset(
                str(REPO_ROOT / "src"), exclude=["**/__pycache__", "*.pyc"]
            ),
            timeout=Duration.minutes(1),
            memory_size=256,
            environment={
                "KILL_FUNCTIONS": self.to_json_string(
                    {function.function_name: limit for function, limit in functions.values()}
                ),
                "KILL_SCHEDULES": self.to_json_string(
                    [["default", schedule.ref] for schedule, _ in schedules]
                ),
            },
            log_group=log_group(self, "KillSwitchLogs"),
        )
        kill.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:PutFunctionConcurrency"],
                resources=[function.function_arn for function, _ in functions.values()],
            )
        )
        kill.add_to_role_policy(
            iam.PolicyStatement(
                actions=["scheduler:GetSchedule", "scheduler:UpdateSchedule"],
                resources=[schedule.attr_arn for schedule, _ in schedules],
            )
        )
        kill.add_to_role_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[role.role_arn for _, role in schedules],
                conditions={"StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}},
            )
        )
        self.kill_switch_topic.add_subscription(subscriptions.LambdaSubscription(kill))
        self.kill_switch = kill

    def _suppressions(self) -> None:
        suppress(
            self,
            {
                "AwsSolutions-SNS2": "CloudWatch alarms and AWS Budgets cannot publish to a topic "
                "encrypted with the AWS-managed SNS key; these topics carry alarm and budget "
                "notices only, never data.",
                "AwsSolutions-IAM4": "The Lambdas use the AWS-managed basic execution role, which "
                "only writes their own logs.",
                "AwsSolutions-IAM5": "Wildcards are scoped to bucket prefixes, and "
                "cloudwatch:PutMetricData (no resource-level permissions) is limited to the "
                "MuleTrace/Drift namespace by condition.",
                "AwsSolutions-L1": "The kill switch uses Python 3.14, like the promotion Lambda; "
                "the newer runtime was not verified as available in Lambda when this was written.",
            },
        )
