"""Training: SageMaker role and image, the model registry, and approval-driven promotion."""

from __future__ import annotations

from typing import Any

from aws_cdk import Duration, Stack
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sagemaker as sagemaker
from constructs import Construct

from infra.stacks.common import REPO_ROOT, log_group, suppress

MODEL_PACKAGE_GROUP = "muletrace-mule-risk"


class TrainingStack(Stack):
    """Everything a Spot training job and a model approval need."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        bucket: s3.IBucket,
        scoring_function: lambda_.IFunction,
        **kwargs: Any,  # noqa: ANN401 - forwarded to cdk.Stack
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.image = ecr_assets.DockerImageAsset(
            self,
            "TrainingImage",
            directory=str(REPO_ROOT),
            file="docker/training.Dockerfile",
            platform=ecr_assets.Platform.LINUX_AMD64,
        )
        self.role = iam.Role(
            self,
            "SageMakerExecutionRole",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            description="MuleTrace training jobs: read snapshots, write models and checkpoints.",
        )
        bucket.grant_read(self.role, "snapshots/*")
        bucket.grant_read_write(self.role, "models/*")
        bucket.grant_read_write(self.role, "checkpoints/*")
        self.image.repository.grant_pull(self.role)
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/sagemaker/TrainingJobs*"
                ],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(actions=["ecr:GetAuthorizationToken"], resources=["*"])
        )

        sagemaker.CfnModelPackageGroup(
            self,
            "ModelPackageGroup",
            model_package_group_name=MODEL_PACKAGE_GROUP,
            model_package_group_description="Daily mule-risk score (LightGBM, synthetic data).",
        )
        self._promotion(bucket, scoring_function)

    def _promotion(self, bucket: s3.IBucket, scoring_function: lambda_.IFunction) -> None:
        promote = lambda_.Function(
            self,
            "PromoteModel",
            runtime=lambda_.Runtime.PYTHON_3_14,
            architecture=lambda_.Architecture.ARM_64,
            handler="muletrace.ops.promote.handler",
            code=lambda_.Code.from_asset(
                str(REPO_ROOT / "src"), exclude=["**/__pycache__", "*.pyc"]
            ),
            timeout=Duration.minutes(2),
            memory_size=512,
            environment={
                "DATA_BUCKET": bucket.bucket_name,
                "SCORING_FUNCTION": scoring_function.function_name,
            },
            log_group=log_group(self, "PromoteModelLogs"),
        )
        bucket.grant_read(promote, "models/*")
        bucket.grant_write(promote, "models/approved/*")
        promote.add_to_role_policy(
            iam.PolicyStatement(
                actions=["sagemaker:DescribeModelPackage"],
                resources=[
                    f"arn:aws:sagemaker:{self.region}:{self.account}:model-package/{MODEL_PACKAGE_GROUP}/*"
                ],
            )
        )
        promote.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:GetFunctionConfiguration", "lambda:UpdateFunctionConfiguration"],
                resources=[scoring_function.function_arn],
            )
        )
        events.Rule(
            self,
            "ModelApproved",
            description="Promote a model when a person approves it in the registry.",
            event_pattern=events.EventPattern(
                source=["aws.sagemaker"],
                detail_type=["SageMaker Model Package State Change"],
                detail={
                    "ModelPackageGroupName": [MODEL_PACKAGE_GROUP],
                    "ModelApprovalStatus": ["Approved"],
                },
            ),
            targets=[targets.LambdaFunction(promote)],
        )
        suppress(
            self,
            {
                "AwsSolutions-IAM4": "The promotion Lambda uses the AWS-managed basic execution "
                "role, which only writes its own logs.",
                "AwsSolutions-L1": "The promotion Lambda uses Python 3.14; the newer 3.15 "
                "runtime was not verified as available in Lambda when this was written. "
                "Revisit when upgrading CDK.",
                "AwsSolutions-IAM5": "Wildcards are scoped to bucket prefixes, to this model "
                "package group, to SageMaker training log groups, and to "
                "ecr:GetAuthorizationToken, which has no resource-level permissions.",
            },
        )
