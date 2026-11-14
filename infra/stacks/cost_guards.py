"""Cost guards: a US$15 budget with alerts, a US$20 deny action and anomaly detection.

AWS has no hard spending cap and billing data lags by hours, so the guards are layered: e-mail
and SNS alerts at 50% (actual), 80% (forecast) and 100% (actual) of US$15, where the kill
switch also stops every function and schedule; at US$20 a budget
action attaches a deny policy to the deployment role so nothing new can be created; and Cost
Anomaly Detection watches every service for unusual daily spend.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_ce as ce
from aws_cdk import aws_iam as iam
from constructs import Construct

from infra.stacks.common import suppress

MONTHLY_BUDGET_USD = 15
DENY_THRESHOLD_USD = 20
ANOMALY_ALERT_USD = 5


def _notification(
    threshold: float, kind: str, email: str, topic_arn: str | None = None
) -> budgets.CfnBudget.NotificationWithSubscribersProperty:
    subscribers = [budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=email)]
    if topic_arn:
        subscribers.append(
            budgets.CfnBudget.SubscriberProperty(subscription_type="SNS", address=topic_arn)
        )
    return budgets.CfnBudget.NotificationWithSubscribersProperty(
        notification=budgets.CfnBudget.NotificationProperty(
            comparison_operator="GREATER_THAN",
            notification_type=kind,
            threshold=threshold,
            threshold_type="PERCENTAGE",
        ),
        subscribers=subscribers,
    )


class CostGuardsStack(Stack):
    """Budget alerts, the deny-at-US$20 action and anomaly detection."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        alert_email: str,
        deployment_role_name: str,
        kill_switch_topic_arn: str | None = None,
        **kwargs: Any,  # noqa: ANN401 - forwarded to cdk.Stack
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="muletrace-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=MONTHLY_BUDGET_USD, unit="USD"),
            ),
            notifications_with_subscribers=[
                _notification(50, "ACTUAL", alert_email),
                _notification(80, "FORECASTED", alert_email),
                # Reaching the budget also pulls the kill switch (see the monitoring stack).
                _notification(100, "ACTUAL", alert_email, kill_switch_topic_arn),
            ],
        )
        self._deny_action(alert_email, deployment_role_name)
        monitor = ce.CfnAnomalyMonitor(
            self,
            "ServiceAnomalyMonitor",
            monitor_name="muletrace-services",
            monitor_type="DIMENSIONAL",
            monitor_dimension="SERVICE",
        )
        ce.CfnAnomalySubscription(
            self,
            "AnomalySubscription",
            subscription_name="muletrace-anomalies",
            frequency="DAILY",
            monitor_arn_list=[monitor.attr_monitor_arn],
            subscribers=[
                ce.CfnAnomalySubscription.SubscriberProperty(type="EMAIL", address=alert_email)
            ],
            threshold_expression=(
                '{"Dimensions": {"Key": "ANOMALY_TOTAL_IMPACT_ABSOLUTE", '
                f'"MatchOptions": ["GREATER_THAN_OR_EQUAL"], "Values": ["{ANOMALY_ALERT_USD}"]}}}}'
            ),
        )

    def _deny_action(self, alert_email: str, deployment_role_name: str) -> None:
        deny = iam.ManagedPolicy(
            self,
            "DenyNewSpend",
            description="Attached by the budget action at US$20: blocks new billable resources.",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.DENY,
                    actions=[
                        "sagemaker:Create*",
                        "lambda:CreateFunction",
                        "lambda:UpdateFunctionCode",
                        "bedrock:InvokeModel*",
                        "bedrock:Converse*",
                        "ec2:RunInstances",
                        "cloudformation:CreateStack",
                        "cloudformation:UpdateStack",
                    ],
                    resources=["*"],
                )
            ],
        )
        action_role = iam.Role(
            self,
            "BudgetActionRole",
            assumed_by=iam.ServicePrincipal("budgets.amazonaws.com"),
        )
        action_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:AttachRolePolicy", "iam:DetachRolePolicy"],
                resources=[f"arn:aws:iam::{self.account}:role/{deployment_role_name}"],
            )
        )
        budgets.CfnBudgetsAction(
            self,
            "DenyAtTwentyDollars",
            budget_name="muletrace-monthly",
            action_type="APPLY_IAM_POLICY",
            action_threshold=budgets.CfnBudgetsAction.ActionThresholdProperty(
                type="ABSOLUTE_VALUE", value=DENY_THRESHOLD_USD
            ),
            approval_model="AUTOMATIC",
            notification_type="ACTUAL",
            execution_role_arn=action_role.role_arn,
            definition=budgets.CfnBudgetsAction.DefinitionProperty(
                iam_action_definition=budgets.CfnBudgetsAction.IamActionDefinitionProperty(
                    policy_arn=deny.managed_policy_arn, roles=[deployment_role_name]
                )
            ),
            subscribers=[
                budgets.CfnBudgetsAction.SubscriberProperty(type="EMAIL", address=alert_email)
            ],
        )
        suppress(
            self,
            {
                "AwsSolutions-IAM5": "The deny policy intentionally uses a wildcard resource: it "
                "must block these actions on every resource once the budget is exceeded.",
            },
        )
