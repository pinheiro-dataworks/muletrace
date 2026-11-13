from pathlib import Path

import pytest

from muletrace.serving import model_source
from muletrace.serving.model_source import download_artifact, resolve_model_dir, split_s3_uri


class _FakeS3:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.calls.append((bucket, key))
        Path(filename).write_text(key, encoding="utf-8")


@pytest.mark.parametrize(
    ("uri", "expected"),
    [("s3://b/models/v1", ("b", "models/v1")), ("s3://b/", ("b", "")), ("s3://b", ("b", ""))],
)
def test_split_s3_uri(uri: str, expected: tuple[str, str]) -> None:
    assert split_s3_uri(uri) == expected


@pytest.mark.parametrize("uri", ["https://b/x", "s3:///x"])
def test_split_rejects_bad_uris(uri: str) -> None:
    with pytest.raises(ValueError, match=r"S3 URI|bucket"):
        split_s3_uri(uri)


def test_download_and_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = _FakeS3()
    folder = download_artifact("s3://bucket/models/v1", tmp_path / "a", s3)
    assert sorted(path.name for path in folder.iterdir()) == sorted(model_source.ARTIFACT_FILES)
    assert s3.calls[0] == ("bucket", "models/v1/model.txt")
    monkeypatch.setattr(model_source, "LOCAL_CACHE", tmp_path / "cache")
    assert resolve_model_dir({"MODEL_URI": "s3://bucket"}, _FakeS3()) == tmp_path / "cache"
    assert resolve_model_dir({"MODEL_DIR": "/somewhere"}) == Path("/somewhere")
    assert resolve_model_dir({}) == Path("/opt/model")
