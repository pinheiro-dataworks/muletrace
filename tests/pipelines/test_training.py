import pytest

from muletrace.pipelines import sagemaker_training, train_entry

SPEC = sagemaker_training.TrainingJobSpec(
    job_name="muletrace-train-1",
    image_uri="123.dkr.ecr.us-east-1.amazonaws.com/train:1",
    role_arn="arn:aws:iam::123:role/sagemaker",
    snapshots_s3_uri="s3://bucket/snapshots/HI-Small/",
    output_s3_uri="s3://bucket/models/",
    checkpoint_s3_uri="s3://bucket/checkpoints/",
    hyperparameters={"num_leaves": 31, "min_data_in_leaf": 50},
)


def test_training_job_request_uses_spot_with_a_hard_limit() -> None:
    request = sagemaker_training.training_job_request(SPEC)
    assert request["EnableManagedSpotTraining"] is True
    assert request["StoppingCondition"] == {
        "MaxRuntimeInSeconds": 1800,
        "MaxWaitTimeInSeconds": 3600,
    }
    assert request["HyperParameters"] == {"num_leaves": "31", "min_data_in_leaf": "50"}
    assert request["CheckpointConfig"]["S3Uri"] == SPEC.checkpoint_s3_uri
    assert {"Key": "Project", "Value": "muletrace"} in request["Tags"]
    with pytest.raises(ValueError, match="max_wait"):
        sagemaker_training.training_job_request(
            sagemaker_training.TrainingJobSpec(**{**SPEC.__dict__, "max_wait_seconds": 60})
        )


def test_model_package_waits_for_manual_approval() -> None:
    request = sagemaker_training.model_package_request(
        "muletrace", SPEC.image_uri, "s3://bucket/models/model.tar.gz", {"valid_ap": 0.2}, "test"
    )
    assert request["ModelApprovalStatus"] == "PendingManualApproval"
    assert request["CustomerMetadataProperties"] == {"valid_ap": "0.2"}

    class Client:
        def create_training_job(self, **kwargs: object) -> dict:
            return {"TrainingJobArn": f"arn:job/{kwargs['TrainingJobName']}"}

        def create_model_package(self, **kwargs: object) -> dict:
            return {"ModelPackageArn": f"arn:package/{kwargs['ModelPackageGroupName']}"}

    assert sagemaker_training.start_training(Client(), SPEC) == "arn:job/muletrace-train-1"
    assert sagemaker_training.register_model(Client(), request) == "arn:package/muletrace"


def test_hyperparameters_are_restored_to_integers() -> None:
    assert train_entry.parse_hyperparameters({"num_leaves": "31", "objective": "binary"}) == {
        "num_leaves": 31,
        "objective": "binary",
    }
