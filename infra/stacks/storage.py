"""Storage: the data bucket, the online feature table and the alerts topic."""

from __future__ import annotations

from typing import Any

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from constructs import Construct

from infra.stacks.common import suppress


class StorageStack(Stack):
    """S3 for data, snapshots, scores and models; DynamoDB for features; SNS for alerts."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        alert_email: str | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.bucket = s3.Bucket(
            self,
            "DataBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            lifecycle_rules=[
                s3.LifecycleRule(noncurrent_version_expiration=Duration.days(30)),
                s3.LifecycleRule(prefix="checkpoints/", expiration=Duration.days(7)),
            ],
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        self.feature_table = dynamodb.TableV2(
            self,
            "FeatureTable",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing=dynamodb.Billing.on_demand(),
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.alerts_topic = sns.Topic(
            self,
            "AlertsTopic",
            display_name="MuleTrace alerts",
            enforce_ssl=True,
            master_key=kms.Alias.from_alias_name(self, "SnsKey", "alias/aws/sns"),
        )
        if alert_email:
            self.alerts_topic.add_subscription(subscriptions.EmailSubscription(alert_email))

        suppress(
            self,
            {
                "AwsSolutions-S1": "Server access logs would cost more than the synthetic data "
                "they protect; CloudTrail data events can be enabled if real data is ever used.",
                "AwsSolutions-DDB3": "Point-in-time recovery is not needed: every item is "
                "rebuilt by the daily batch job from S3.",
                "AwsSolutions-IAM4": "The auto-delete custom resource uses the AWS-managed basic "
                "execution role created by CDK.",
                "AwsSolutions-L1": "The auto-delete custom resource runtime is managed by CDK.",
            },
        )
