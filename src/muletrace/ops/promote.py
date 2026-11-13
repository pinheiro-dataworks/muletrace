"""Promote an approved model: approval in the model registry is the deployment trigger.

EventBridge sends a "SageMaker Model Package State Change" event when a person approves a
model package. This function then:

1. reads the package's ``model.tar.gz`` location,
2. unpacks the three artefact files into ``models/approved/<package version>/`` in the bucket,
3. points the scoring Lambda's ``MODEL_URI`` at that prefix.

The next cold start of the scoring Lambda loads the new model. Rolling back is approving (or
re-approving) an earlier package version. Clients are injectable so the logic is tested locally.
"""

from __future__ import annotations

import os
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from muletrace.models.artifact_files import ARTIFACT_FILES
from muletrace.serving.model_source import split_s3_uri


def approved_package_arn(event: dict[str, Any]) -> str | None:
    """The package ARN if the event is an approval, otherwise ``None``."""
    detail = event.get("detail", {})
    if detail.get("ModelApprovalStatus") != "Approved":
        return None
    return str(detail["ModelPackageArn"])


def _safe_extract(archive: Path, destination: Path) -> None:
    """Extract only the artefact files, refusing any path outside ``destination``."""
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            name = Path(member.name).name
            if member.isfile() and name in ARTIFACT_FILES:
                source = bundle.extractfile(member)
                if source is not None:
                    (destination / name).write_bytes(source.read())


def promote(
    event: dict[str, Any],
    *,
    sagemaker: Any,  # noqa: ANN401 - boto3 clients
    s3: Any,  # noqa: ANN401
    lambda_client: Any,  # noqa: ANN401
    bucket: str,
    function_name: str,
) -> dict[str, Any]:
    """Publish an approved package's artefact and repoint the scoring Lambda."""
    arn = approved_package_arn(event)
    if arn is None:
        return {"promoted": False, "reason": "not an approval"}
    package = sagemaker.describe_model_package(ModelPackageName=arn)
    version = package.get("ModelPackageVersion", arn.rsplit("/", 1)[-1])
    model_url = package["InferenceSpecification"]["Containers"][0]["ModelDataUrl"]
    source_bucket, key = split_s3_uri(model_url)
    prefix = f"models/approved/{version}"
    with tempfile.TemporaryDirectory() as work:
        archive = Path(work) / "model.tar.gz"
        s3.download_file(source_bucket, key, str(archive))
        _safe_extract(archive, Path(work))
        for name in ARTIFACT_FILES:
            s3.upload_file(str(Path(work) / name), bucket, f"{prefix}/{name}")
    current = lambda_client.get_function_configuration(FunctionName=function_name)
    variables = {
        **current.get("Environment", {}).get("Variables", {}),
        "MODEL_URI": f"s3://{bucket}/{prefix}",
    }
    lambda_client.update_function_configuration(
        FunctionName=function_name, Environment={"Variables": variables}
    )
    return {"promoted": True, "model_uri": variables["MODEL_URI"], "package": arn}


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:  # pragma: no cover
    """Lambda entry point for the EventBridge rule."""
    import boto3  # noqa: PLC0415

    return promote(
        event,
        sagemaker=boto3.client("sagemaker"),
        s3=boto3.client("s3"),
        lambda_client=boto3.client("lambda"),
        bucket=os.environ["DATA_BUCKET"],
        function_name=os.environ["SCORING_FUNCTION"],
    )
