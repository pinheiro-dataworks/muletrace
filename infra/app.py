"""CDK application: every MuleTrace stack in us-east-1, tagged and checked by cdk-nag.

Context values (``cdk.json`` or ``-c key=value``):

* ``alert_email`` — where budget, anomaly and pipeline alerts go (required for cost guards);
* ``deployment_role_name`` — the GitHub OIDC deployment role the US$20 budget action restricts;
* ``env_name`` — ``dev`` or ``prod``, used in tags.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from infra.stacks.cost_guards import CostGuardsStack
from infra.stacks.pipeline import PipelineStack
from infra.stacks.serving import ServingStack
from infra.stacks.storage import StorageStack
from infra.stacks.training import TrainingStack

REGION = "us-east-1"


def build_app(app: cdk.App) -> list[cdk.Stack]:
    """Create every stack on ``app``; returns them in deployment order."""
    env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=REGION)
    alert_email = app.node.try_get_context("alert_email")
    env_name = app.node.try_get_context("env_name") or "dev"

    storage = StorageStack(app, "MuleTrace-Storage", env=env, alert_email=alert_email)
    serving = ServingStack(
        app,
        "MuleTrace-Serving",
        env=env,
        bucket=storage.bucket,
        feature_table=storage.feature_table,
    )
    training = TrainingStack(
        app, "MuleTrace-Training", env=env, bucket=storage.bucket, scoring_function=serving.scorer
    )
    pipeline = PipelineStack(
        app,
        "MuleTrace-Pipeline",
        env=env,
        bucket=storage.bucket,
        feature_table=storage.feature_table,
        alerts_topic=storage.alerts_topic,
    )
    stacks: list[cdk.Stack] = [storage, serving, training, pipeline]
    if alert_email:
        stacks.append(
            CostGuardsStack(
                app,
                "MuleTrace-CostGuards",
                env=env,
                alert_email=alert_email,
                deployment_role_name=app.node.try_get_context("deployment_role_name")
                or "muletrace-github-deploy",
            )
        )

    for key, value in {
        "Project": "muletrace",
        "Env": env_name,
        "Owner": "renan-pinheiro",
        "TTL": "archive-after-v1",
    }.items():
        cdk.Tags.of(app).add(key, value)
    cdk.Aspects.of(app).add(AwsSolutionsChecks(verbose=True))
    return stacks


if __name__ == "__main__":
    application = cdk.App()
    build_app(application)
    application.synth()
