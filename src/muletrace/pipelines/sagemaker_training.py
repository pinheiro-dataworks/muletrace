"""Cloud training: a SageMaker training job on Spot capacity, then a model-registry entry.

Requests are built by pure functions so they can be reviewed and tested without AWS; the thin
``start_training`` and ``register_model`` wrappers send them with a boto3 client. The job runs the
same :func:`muletrace.models.final.train_final_model` as a local run (see ``train_entry``), uses
managed Spot training with checkpointing and a hard maximum runtime, and the trained model is
registered as ``PendingManualApproval``: nothing is deployed until a person approves it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

PROJECT_TAG: Final = {"Key": "Project", "Value": "muletrace"}
APPROVAL_PENDING: Final = "PendingManualApproval"


@dataclass(frozen=True)
class TrainingJobSpec:
    """Everything a training job needs; defaults keep a run to cents."""

    job_name: str
    image_uri: str
    role_arn: str
    snapshots_s3_uri: str
    output_s3_uri: str
    checkpoint_s3_uri: str
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    instance_type: str = "ml.m5.xlarge"
    volume_gb: int = 10
    max_runtime_seconds: int = 1800
    max_wait_seconds: int = 3600


def training_job_request(spec: TrainingJobSpec) -> dict[str, Any]:
    """``CreateTrainingJob`` parameters for a managed Spot run."""
    if spec.max_wait_seconds < spec.max_runtime_seconds:
        raise ValueError("Spot jobs need max_wait_seconds >= max_runtime_seconds")
    return {
        "TrainingJobName": spec.job_name,
        "AlgorithmSpecification": {"TrainingImage": spec.image_uri, "TrainingInputMode": "File"},
        "RoleArn": spec.role_arn,
        "HyperParameters": {key: str(value) for key, value in spec.hyperparameters.items()},
        "InputDataConfig": [
            {
                "ChannelName": "snapshots",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": spec.snapshots_s3_uri,
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
                "ContentType": "application/x-parquet",
            }
        ],
        "OutputDataConfig": {"S3OutputPath": spec.output_s3_uri},
        "ResourceConfig": {
            "InstanceType": spec.instance_type,
            "InstanceCount": 1,
            "VolumeSizeInGB": spec.volume_gb,
        },
        "StoppingCondition": {
            "MaxRuntimeInSeconds": spec.max_runtime_seconds,
            "MaxWaitTimeInSeconds": spec.max_wait_seconds,
        },
        "EnableManagedSpotTraining": True,
        "CheckpointConfig": {"S3Uri": spec.checkpoint_s3_uri},
        "Tags": [PROJECT_TAG],
    }


def model_package_request(
    group_name: str,
    image_uri: str,
    model_data_url: str,
    metrics: dict[str, float | int | str],
    description: str,
) -> dict[str, Any]:
    """``CreateModelPackage`` parameters; the package waits for manual approval."""
    return {
        "ModelPackageGroupName": group_name,
        "ModelPackageDescription": description,
        "InferenceSpecification": {
            "Containers": [{"Image": image_uri, "ModelDataUrl": model_data_url}],
            "SupportedContentTypes": ["application/json"],
            "SupportedResponseMIMETypes": ["application/json"],
        },
        "ModelApprovalStatus": APPROVAL_PENDING,
        "CustomerMetadataProperties": {key: str(value) for key, value in metrics.items()},
        "Tags": [PROJECT_TAG],
    }


def start_training(client: Any, spec: TrainingJobSpec) -> str:  # noqa: ANN401 - boto3 client
    """Start the job and return its ARN."""
    response = client.create_training_job(**training_job_request(spec))
    return str(response["TrainingJobArn"])


def register_model(client: Any, request: dict[str, Any]) -> str:  # noqa: ANN401 - boto3 client
    """Register a trained model and return the model-package ARN."""
    response = client.create_model_package(**request)
    return str(response["ModelPackageArn"])
