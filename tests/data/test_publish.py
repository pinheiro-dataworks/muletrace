from pathlib import Path

import polars as pl
import pytest
import yaml

from muletrace.config import CONFIG_DIR, load_config
from muletrace.data import pix_layer_simulator
from muletrace.data.amlworld_loader import RawDataset
from muletrace.data.labels import LabelConfig
from muletrace.data.manifest import sha256_of
from muletrace.data.prepare import prepare_dataset
from muletrace.data.publish import PIX_TABLES, export_bundle
from tests.fixtures.amlworld import write_amlworld_files


@pytest.fixture(scope="module")
def dataset_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("publish")
    prepared = prepare_dataset(
        RawDataset("HI-Small", write_amlworld_files(base / "raw")), base / "p"
    ).output_dir
    pix_layer_simulator.run(
        prepared,
        load_config(pix_layer_simulator.SimulatorConfig, CONFIG_DIR / "simulator.yaml"),
        load_config(LabelConfig, CONFIG_DIR / "labels.yaml"),
    )
    return prepared


def test_bundle_holds_the_layer_the_card_the_licence_and_checksums(
    dataset_dir: Path, tmp_path: Path
) -> None:
    card, licence = tmp_path / "card.md", tmp_path / "LICENCE.txt"
    card.write_text("# card\n", "utf-8")
    licence.write_text("CDLA-Sharing-1.0\n", "utf-8")
    output = tmp_path / "bundle"
    manifest = export_bundle([dataset_dir], card, licence, output)
    paths = {row["path"] for row in manifest["files"]}
    assert paths == {
        "README.md",
        "LICENSE",
        "HI-Small/account_map.parquet",
        "HI-Small/calibration_report.yaml",
        *(f"HI-Small/{name}.parquet" for name in PIX_TABLES),
    }
    for row in manifest["files"]:
        assert sha256_of(output / row["path"]) == row["sha256"]
    assert yaml.safe_load((output / "MANIFEST.yaml").read_text("utf-8")) == manifest
    account_map = pl.read_parquet(output / "HI-Small/account_map.parquet")
    assert account_map.columns == ["account_id", "bank_id", "account_number"]
    for name in PIX_TABLES:  # the layer never carries AMLworld's label column itself
        columns = pl.read_parquet(output / f"HI-Small/{name}.parquet").columns
        assert not {"is_laundering", "label"} & set(columns)

    export_bundle([dataset_dir], card, licence, output)  # a previous bundle is rebuilt
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    with pytest.raises(FileExistsError, match="not a previous bundle"):
        export_bundle([dataset_dir], card, licence, unrelated)
