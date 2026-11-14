"""Checksum manifest for the raw AMLworld files.

``data/MANIFEST.yaml`` is committed to Git. It pins every source file by size and SHA-256, so a
fresh clone can prove that it is working on exactly the same bytes, and it records where the
data came from and under which licence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import yaml

KAGGLE_DATASET: Final = "ealtman2019/ibm-transactions-for-anti-money-laundering-aml"
SOURCE: Final = {
    "name": "IBM AMLworld (IBM Transactions for Anti Money Laundering)",
    "publisher": "IBM Research",
    "kaggle_dataset": KAGGLE_DATASET,
    "url": f"https://www.kaggle.com/datasets/{KAGGLE_DATASET}",
    "paper": "Altman et al., Realistic Synthetic Financial Transactions for Anti-Money "
    "Laundering Models, arXiv:2306.16424",
    "licence": "CDLA-Sharing-1.0",
    "licence_file": "data/LICENSES/CDLA-Sharing-1.0.txt",
}
_CHUNK_BYTES: Final = 1 << 20


class ManifestMismatchError(RuntimeError):
    """Raised when a raw file is missing or differs from the manifest."""


@dataclass(frozen=True)
class FileRecord:
    """Size, checksum and provenance of one source file."""

    name: str
    bytes: int
    sha256: str
    data_rows: int | None
    downloaded_on: str

    def as_dict(self) -> dict[str, Any]:
        """Return a YAML-friendly mapping."""
        return {
            "name": self.name,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "data_rows": self.data_rows,
            "downloaded_on": self.downloaded_on,
        }


def sha256_of(path: Path) -> str:
    """Stream a file through SHA-256 in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def count_data_rows(path: Path) -> int:
    """Count lines after the header of a CSV file."""
    with path.open("rb") as handle:
        lines = sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""))
    return lines - 1


def describe_file(path: Path) -> FileRecord:
    """Build the manifest record for one file.

    ``downloaded_on`` is the file's modification date in UTC, which is the date the Kaggle
    download wrote it.
    """
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).date()
    return FileRecord(
        name=path.name,
        bytes=path.stat().st_size,
        sha256=sha256_of(path),
        data_rows=count_data_rows(path) if path.suffix == ".csv" else None,
        downloaded_on=modified.isoformat(),
    )


def write_manifest(files: list[Path], manifest_path: Path, generated_on: date) -> dict[str, Any]:
    """Describe ``files`` and write the manifest; returns the written mapping."""
    manifest = {
        "source": SOURCE,
        "generated_on": generated_on.isoformat(),
        "files": [describe_file(path).as_dict() for path in sorted(files)],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8", newline="\n"
    )
    return manifest


def verify_manifest(manifest_path: Path, raw_dir: Path) -> list[str]:
    """Check every file listed in the manifest; returns the names that were verified.

    Raises:
        ManifestMismatchError: if a file is missing or its size or checksum differs.
    """
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    verified: list[str] = []
    for record in manifest["files"]:
        path = raw_dir / record["name"]
        if not path.is_file():
            raise ManifestMismatchError(f"missing raw file: {path}")
        if path.stat().st_size != record["bytes"] or sha256_of(path) != record["sha256"]:
            raise ManifestMismatchError(f"checksum mismatch: {path}")
        verified.append(record["name"])
    return verified
