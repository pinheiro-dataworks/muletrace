"""Where the scoring Lambda gets its model artefact.

The approved model lives in S3 (``MODEL_URI=s3://bucket/prefix``); the Lambda downloads its three
files to ``/tmp`` on the first request of a container. Promoting a new model is then a matter of
changing ``MODEL_URI``, which the approval workflow does, and the image never contains a model.
For local runs ``MODEL_DIR`` points at a folder instead.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from muletrace.models.artifact import CALIBRATOR_FILE, METADATA_FILE, MODEL_FILE

ARTIFACT_FILES = (MODEL_FILE, CALIBRATOR_FILE, METADATA_FILE)
# /tmp is the only writable path in Lambda and is private to each execution environment.
LOCAL_CACHE = Path("/tmp/muletrace-model")  # noqa: S108  # nosec B108


def split_s3_uri(uri: str) -> tuple[str, str]:
    """``s3://bucket/some/prefix`` → ``("bucket", "some/prefix")``."""
    if not uri.startswith("s3://"):
        raise ValueError(f"not an S3 URI: {uri!r}")
    bucket, _, prefix = uri.removeprefix("s3://").partition("/")
    if not bucket:
        raise ValueError(f"missing bucket in {uri!r}")
    return bucket, prefix.strip("/")


def download_artifact(uri: str, destination: Path, s3_client: Any | None = None) -> Path:  # noqa: ANN401
    """Download the artefact files under an S3 prefix into ``destination``."""
    if s3_client is None:
        import boto3  # noqa: PLC0415 - only the AWS path needs it

        s3_client = boto3.client("s3")
    bucket, prefix = split_s3_uri(uri)
    destination.mkdir(parents=True, exist_ok=True)
    for name in ARTIFACT_FILES:
        key = f"{prefix}/{name}" if prefix else name
        s3_client.download_file(bucket, key, str(destination / name))
    return destination


def resolve_model_dir(environ: dict[str, str] | None = None, s3_client: Any | None = None) -> Path:  # noqa: ANN401
    """Model folder for this container: from ``MODEL_URI`` (downloaded) or ``MODEL_DIR``."""
    env = dict(os.environ) if environ is None else environ
    if uri := env.get("MODEL_URI"):
        return download_artifact(uri, LOCAL_CACHE, s3_client)
    return Path(env.get("MODEL_DIR", "/opt/model"))
