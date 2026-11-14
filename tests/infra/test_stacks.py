"""Synthesise every stack, check the properties that matter and that cdk-nag reports no errors."""

import pytest

cdk = pytest.importorskip("aws_cdk")

from aws_cdk.assertions import Annotations, Match, Template  # noqa: E402
from infra.app import build_app  # noqa: E402


@pytest.fixture(scope="module")
def stacks() -> dict[str, object]:
    app = cdk.App(context={"alert_email": "alerts@example.invalid"})
    built = build_app(app)
    return {stack.stack_name: stack for stack in built}


def test_every_stack_is_nag_clean(stacks: dict[str, object]) -> None:
    for name, stack in stacks.items():
        errors = Annotations.from_stack(stack).find_error(
            "*", Match.string_like_regexp("AwsSolutions-.*")
        )
        assert errors == [], f"{name}: {[e.entry.data for e in errors]}"


def test_scorer_is_arm64_with_capped_concurrency(stacks: dict[str, object]) -> None:
    template = Template.from_stack(stacks["MuleTrace-Serving"])
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {"Architectures": ["arm64"], "ReservedConcurrentExecutions": 5, "MemorySize": 1024},
    )
    template.has_resource_properties(
        "AWS::ApiGatewayV2::Stage",
        {"DefaultRouteSettings": {"ThrottlingRateLimit": 5, "ThrottlingBurstLimit": 10}},
    )
    template.has_resource_properties("AWS::ApiGatewayV2::Route", {"AuthorizationType": "AWS_IAM"})


def test_storage_is_private_and_on_demand(stacks: dict[str, object]) -> None:
    template = Template.from_stack(stacks["MuleTrace-Storage"])
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )
    template.has_resource_properties(
        "AWS::DynamoDB::GlobalTable", {"BillingMode": "PAY_PER_REQUEST"}
    )


def test_daily_schedule_starts_disabled(stacks: dict[str, object]) -> None:
    template = Template.from_stack(stacks["MuleTrace-Pipeline"])
    template.has_resource_properties("AWS::Scheduler::Schedule", {"State": "DISABLED"})
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)


def test_approval_triggers_promotion(stacks: dict[str, object]) -> None:
    template = Template.from_stack(stacks["MuleTrace-Training"])
    template.has_resource_properties(
        "AWS::Events::Rule",
        {"EventPattern": {"detail": {"ModelApprovalStatus": ["Approved"]}}},
    )
    template.resource_count_is("AWS::SageMaker::ModelPackageGroup", 1)


def test_cost_guards(stacks: dict[str, object]) -> None:
    template = Template.from_stack(stacks["MuleTrace-CostGuards"])
    template.has_resource_properties(
        "AWS::Budgets::Budget",
        {"Budget": {"BudgetLimit": {"Amount": 15, "Unit": "USD"}}},
    )
    template.has_resource_properties(
        "AWS::Budgets::BudgetsAction",
        {"ActionThreshold": {"Type": "ABSOLUTE_VALUE", "Value": 20}},
    )
    template.resource_count_is("AWS::CE::AnomalyMonitor", 1)


def test_every_resource_is_tagged(stacks: dict[str, object]) -> None:
    template = Template.from_stack(stacks["MuleTrace-Storage"])
    template.has_resource_properties(
        "AWS::S3::Bucket", {"Tags": Match.array_with([{"Key": "Project", "Value": "muletrace"}])}
    )


def test_copilot_is_guarded_and_scoped_to_one_model(stacks: dict[str, object]) -> None:
    template = Template.from_stack(stacks["MuleTrace-Agents"])
    template.has_resource_properties(
        "AWS::Bedrock::Guardrail",
        {
            "ContentPolicyConfig": {
                "FiltersConfig": [
                    {"Type": "PROMPT_ATTACK", "InputStrength": "HIGH", "OutputStrength": "NONE"}
                ]
            },
            "TopicPolicyConfig": {
                "TopicsConfig": [Match.object_like({"Name": "ReleasingFunds", "Type": "DENY"})]
            },
        },
    )
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "ImageConfig": {"Command": ["muletrace.agents.handler.handler"]},
            "ReservedConcurrentExecutions": 2,
            "Environment": {
                "Variables": Match.object_like({"AGENT_MODEL_ID": "amazon.nova-lite-v1:0"})
            },
        },
    )
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "bedrock:InvokeModel",
                                "Resource": Match.string_like_regexp(
                                    "foundation-model/amazon.nova-lite-v1:0$"
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )
