import io
import tarfile
from pathlib import Path

from muletrace.ops.promote import approved_package_arn, promote

ARN = "arn:aws:sagemaker:us-east-1:123:model-package/muletrace/3"


def _archive(path: Path) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        for name in ("model.txt", "calibrator.json", "metadata.json", "../evil.sh"):
            data = name.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))


class FakeClients:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.uploaded: dict[str, bytes] = {}
        self.environment: dict[str, str] = {"FEATURE_TABLE": "features"}

    def describe_model_package(self, ModelPackageName: str) -> dict:  # noqa: N803
        assert ModelPackageName == ARN
        return {
            "ModelPackageVersion": 3,
            "InferenceSpecification": {
                "Containers": [{"ModelDataUrl": "s3://train/out/model.tar.gz"}]
            },
        }

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        assert (bucket, key) == ("train", "out/model.tar.gz")
        _archive(Path(filename))

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.uploaded[f"{bucket}/{key}"] = Path(filename).read_bytes()

    def get_function_configuration(self, FunctionName: str) -> dict:  # noqa: N803
        assert FunctionName == "scorer"
        return {"Environment": {"Variables": dict(self.environment)}}

    def update_function_configuration(self, FunctionName: str, Environment: dict) -> None:  # noqa: N803
        assert FunctionName == "scorer"
        self.environment = Environment["Variables"]


def _clients(clients: FakeClients) -> dict:
    return {
        "sagemaker": clients,
        "s3": clients,
        "lambda_client": clients,
        "bucket": "data",
        "function_name": "scorer",
    }


def _event(status: str) -> dict:
    return {"detail": {"ModelApprovalStatus": status, "ModelPackageArn": ARN}}


def test_only_approvals_promote(tmp_path: Path) -> None:
    clients = FakeClients(tmp_path)
    assert approved_package_arn(_event("Rejected")) is None
    result = promote(_event("PendingManualApproval"), **_clients(clients))
    assert result["promoted"] is False
    assert clients.uploaded == {}


def test_approval_publishes_artifact_and_repoints_the_scorer(tmp_path: Path) -> None:
    clients = FakeClients(tmp_path)
    result = promote(_event("Approved"), **_clients(clients))
    assert result == {"promoted": True, "model_uri": "s3://data/models/approved/3", "package": ARN}
    assert sorted(clients.uploaded) == [
        "data/models/approved/3/calibrator.json",
        "data/models/approved/3/metadata.json",
        "data/models/approved/3/model.txt",
    ]
    assert clients.environment == {
        "FEATURE_TABLE": "features",
        "MODEL_URI": "s3://data/models/approved/3",
    }


def test_promotion_does_not_import_heavy_libraries() -> None:
    """The promotion Lambda runs on the plain Python runtime: no LightGBM, NumPy or Polars."""
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    code = (
        "import sys, muletrace.ops.promote; "
        "heavy = {'lightgbm', 'numpy', 'polars', 'pydantic', 'yaml'} & set(sys.modules); "
        "print(sorted(heavy))"
    )
    output = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert output == "[]"
