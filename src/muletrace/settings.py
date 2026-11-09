"""Filesystem locations shared by every pipeline stage.

Paths come from environment variables so that the same code runs on a laptop, in CI and in a
SageMaker job. A local ``.env`` file is read when present; variables already set in the
environment always win.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ENV_FILE = Path(".env")


def load_env_file(path: Path = DEFAULT_ENV_FILE) -> None:
    """Load ``KEY=VALUE`` lines from ``path`` into ``os.environ`` without overriding.

    Blank lines and lines starting with ``#`` are ignored. Values may be wrapped in single or
    double quotes. The file is optional.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass(frozen=True)
class Settings:
    """Resolved directories for raw inputs, processed data and artefacts."""

    raw_dir: Path
    data_dir: Path
    artifacts_dir: Path

    @property
    def processed_dir(self) -> Path:
        """Folder for Parquet files produced by the ingestion stage."""
        return self.data_dir / "processed"

    @property
    def features_dir(self) -> Path:
        """Cache of point-in-time feature snapshots."""
        return self.artifacts_dir / "features"

    @property
    def manifest_path(self) -> Path:
        """Location of the checksum manifest that is committed to Git."""
        return self.data_dir / "MANIFEST.yaml"

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables, falling back to repository defaults."""
        data_dir = Path(os.environ.get("MULETRACE_DATA_DIR", "data"))
        return cls(
            raw_dir=Path(os.environ.get("MULETRACE_RAW_DIR", str(data_dir / "raw"))),
            data_dir=data_dir,
            artifacts_dir=Path(os.environ.get("MULETRACE_ARTIFACTS_DIR", "artifacts")),
        )
