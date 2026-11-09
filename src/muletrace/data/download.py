"""Download AMLworld files from Kaggle with the official Kaggle CLI.

The Kaggle CLI reads credentials from ``~/.kaggle`` (or ``KAGGLE_*`` environment variables);
MuleTrace never stores them. Files already present are left untouched, and the manifest check
that follows a download is what proves the bytes are the expected ones.
"""

from __future__ import annotations

import logging
import shutil

# subprocess is used only to call the Kaggle CLI with a fixed argument list and no shell.
import subprocess  # nosec B404
from pathlib import Path

from muletrace.data.amlworld_loader import RawDataset
from muletrace.data.manifest import KAGGLE_DATASET

logger = logging.getLogger(__name__)


class KaggleCliNotFoundError(RuntimeError):
    """Raised when the ``kaggle`` executable is not on ``PATH``."""


def missing_files(datasets: list[RawDataset]) -> list[Path]:
    """Return the source files that are not yet on disk."""
    return [path for dataset in datasets for path in dataset.files if not path.is_file()]


def download_missing(datasets: list[RawDataset]) -> list[Path]:
    """Download every missing source file; returns the paths that were downloaded."""
    to_fetch = missing_files(datasets)
    if not to_fetch:
        logger.info("All raw files already present; nothing to download.")
        return []
    kaggle = shutil.which("kaggle")
    if kaggle is None:
        raise KaggleCliNotFoundError("Install the Kaggle CLI (`pip install kaggle`) and log in.")
    for path in to_fetch:
        path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            kaggle,
            "datasets",
            "download",
            KAGGLE_DATASET,
            "--file",
            path.name,
            "--path",
            str(path.parent),
            "--unzip",
        ]
        logger.info("Downloading %s", path.name)
        subprocess.run(command, check=True)  # noqa: S603  # nosec B603
    return to_fetch
