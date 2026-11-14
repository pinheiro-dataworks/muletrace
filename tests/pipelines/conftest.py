"""A generated world, prepared into a fake S3 bucket layout."""

from pathlib import Path

import pytest

from muletrace.data.amlworld_loader import RawDataset
from muletrace.data.prepare import prepare_dataset
from tests.fixtures.world import generate_world


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("daily")
    prepare_dataset(
        RawDataset("HI-Small", generate_world(base / "raw")), base / "bucket" / "data" / "processed"
    )
    return base
