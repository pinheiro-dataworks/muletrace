"""Investigation copilot: a Bedrock Guardrail and the Lambda that drafts case files.

The copilot model, its prices and the token budget come from ``configs/copilot.yaml``, the same
file the evaluation harness reads, so the deployed copilot is the one that was evaluated.

What the guardrail covers, and what it does not (see ADR-011):

* prompt attacks are filtered on inputs the model reads as text. Tool results are not evaluated
  by a guardrail attached through the Converse API, so customer-written descriptions returned by
  ``get_transfers`` are handled by the prompts and the deterministic fact checker instead;
* e-mail addresses and phone numbers are anonymised in model outputs only, so evidence numbers
  in the inputs are never rewritten;
* recommending to release or return funds is a denied topic;
* contextual grounding is not configured: it needs grounding sources tagged in the request, and
  every cited figure is already verified exactly by the fact checker.
"""

from __future__ import annotations

import json
from typing import Any

from aws_cdk import Duration, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

from infra.stacks.common import REPO_ROOT, log_group, suppress
from muletrace.config import CONFIG_DIR, load_config
from muletrace.evals.runner import CopilotConfig

COPILOT_MEMORY_MB = 512
COPILOT_CONCURRENCY = 2
COPILOT_TIMEOUT = Duration.seconds(60)


class AgentsStack(Stack):
    """The copilot Lambda and the guardrail every Bedrock call goes through."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs: Any,  # noqa: ANN401 - forwarded to cdk.Stack
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        config = load_config(CopilotConfig, CONFIG_DIR / "copilot.yaml")
        self.guardrail = self._guardrail()
        self.guardrail_version = bedrock.CfnGuardrailVersion(
            self,
            "CopilotGuardrailVersion",
            guardrail_identifier=self.guardrail.attr_guardrail_id,
            description="Version used by the copilot Lambda.",
        )
        image = ecr_assets.DockerImageAsset(
            self,
            "CopilotImage",
            directory=str(REPO_ROOT),
            file="docker/lambda.Dockerfile",
            platform=ecr_assets.Platform.LINUX_ARM64,
        )
        self.copilot = lambda_.DockerImageFunction(
            self,
            "Copilot",
            code=lambda_.DockerImageCode.from_ecr(
                image.repository,
                tag_or_digest=image.image_tag,
                cmd=["muletrace.agents.handler.handler"],
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=COPILOT_MEMORY_MB,
            timeout=COPILOT_TIMEOUT,
            reserved_concurrent_executions=COPILOT_CONCURRENCY,
            environment={
                "AGENT_MODEL_ID": config.agent_model,
                "AGENT_MODEL_PRICE": json.dumps(config.prices[config.agent_model].model_dump()),
                "BEDROCK_GUARDRAIL_ID": self.guardrail.attr_guardrail_id,
                "BEDROCK_GUARDRAIL_VERSION": self.guardrail_version.attr_version,
                "TOKEN_BUDGET_PER_CASE": str(config.token_budget_per_case),
            },
            log_group=log_group(self, "CopilotLogs"),
            tracing=lambda_.Tracing.ACTIVE,
        )
        self.copilot.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[f"arn:aws:bedrock:{self.region}::foundation-model/{config.agent_model}"],
            )
        )
        self.copilot.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:ApplyGuardrail"], resources=[self.guardrail.attr_guardrail_arn]
            )
        )
        suppress(
            self,
            {
                "AwsSolutions-IAM4": "The copilot uses the AWS-managed basic execution and X-Ray "
                "policies, which grant only log and trace writes.",
                "AwsSolutions-IAM5": "X-Ray has no resource-level permissions; Bedrock access is "
                "limited to one foundation model and one guardrail.",
            },
        )

    def _guardrail(self) -> bedrock.CfnGuardrail:
        blocked = "The copilot cannot process this case. An analyst must review it manually."
        return bedrock.CfnGuardrail(
            self,
            "CopilotGuardrail",
            name="muletrace-copilot",
            description="Investigation copilot: prompt attacks, PII in drafts, fund release.",
            blocked_input_messaging=blocked,
            blocked_outputs_messaging=blocked,
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    # Prompt-attack filtering applies to inputs only; output strength must be NONE.
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="PROMPT_ATTACK", input_strength="HIGH", output_strength="NONE"
                    )
                ]
            ),
            sensitive_information_policy_config=(
                bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                    pii_entities_config=[
                        bedrock.CfnGuardrail.PiiEntityConfigProperty(
                            type=entity,
                            action="ANONYMIZE",
                            input_enabled=False,
                            output_enabled=True,
                            output_action="ANONYMIZE",
                        )
                        for entity in ("EMAIL", "PHONE")
                    ]
                )
            ),
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="ReleasingFunds",
                        type="DENY",
                        definition=(
                            "Recommending or instructing that blocked or held funds be "
                            "released, returned or paid out to the account holder."
                        ),
                        examples=[
                            "Release the funds to the customer.",
                            "The hold can be lifted and the money paid out.",
                        ],
                        input_enabled=False,
                        output_enabled=True,
                        output_action="BLOCK",
                    )
                ]
            ),
        )
