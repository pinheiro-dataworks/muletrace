from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from muletrace.config import CONFIG_DIR, load_config
from muletrace.data import pix_layer_simulator as sim
from muletrace.data.amlworld_loader import RawDataset
from muletrace.data.labels import LabelConfig, confirmations, mule_events
from muletrace.data.prepare import prepare_dataset
from tests.fixtures.amlworld import Tx, write_amlworld_files

# Busy enough to produce disputes: a source account sends laundered money at night
# to an individual, who forwards it; plenty of ordinary transfers around it.
ROWS = (
    Tx(
        "2022/09/01 00:00",
        "001",
        "S",
        "002",
        "U",
        10.0,
        received_amount=8.5,
        received_currency="Euro",
    ),
    Tx(
        "2022/09/01 00:00",
        "001",
        "S",
        "002",
        "U",
        10.0,
        currency="Brazil Real",
        received_amount=1.77,
        received_currency="US Dollar",
    ),
    Tx("2022/09/01 21:00", "001", "S", "002", "M", 500.0, is_laundering=1),
    Tx("2022/09/01 22:00", "002", "M", "003", "N", 450.0, is_laundering=1),
    Tx("2022/09/01 12:00", "002", "M", "002", "M", 40.0, payment_format="Reinvestment"),
    *(Tx(f"2022/09/02 {h:02d}:00", "004", f"P{h}", "005", f"Q{h}", 20.0 + h) for h in range(20)),
)
ACCOUNTS = (
    ("Bank #1", "1", "S", "E1", "Corporation #1"),
    ("Bank #2", "2", "M", "E2", "Individual #2"),
    ("Bank #3", "3", "N", "E3", "Individual #3"),
    ("Bank #2", "2", "U", "E4", "Sole Proprietorship #4"),
)
TARGETS = sim.CalibrationTargets(
    accepted_per_100k=5_000.0,  # one accepted dispute on ~25 instant transfers
    rejection_share=0.5,
    mean_accepted_ticket_brl=2_000.0,
    key_mix={"PF": {"Aleatória": 0.5, "e-mail": 0.5}, "PJ": {"CNPJ": 0.7, "Celular": 0.3}},
)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("pix")
    raw = RawDataset(
        "HI-Small",
        write_amlworld_files(base / "raw", transactions=ROWS, accounts=ACCOUNTS, patterns=""),
    )
    return prepare_dataset(raw, base / "processed").output_dir


@pytest.fixture(scope="module")
def config() -> sim.SimulatorConfig:
    return load_config(sim.SimulatorConfig, CONFIG_DIR / "simulator.yaml")


def _simulate(prepared: Path, config: sim.SimulatorConfig) -> sim.PixLayer:
    transactions = pl.read_parquet(prepared / "transactions.parquet")
    mules = confirmations(mule_events(transactions.lazy()), timedelta(hours=24))
    return sim.simulate(
        transactions=transactions,
        accounts=pl.read_parquet(prepared / "accounts.parquet"),
        brl_per_usd=5.6465,
        mules=mules,
        config=config,
        targets=TARGETS,
    )


def test_same_seed_gives_identical_tables(prepared: Path, config: sim.SimulatorConfig) -> None:
    first, second = _simulate(prepared, config), _simulate(prepared, config)
    for name in ("transfers", "keys", "dict_markings", "disputes"):
        assert_frame_equal(getattr(first, name), getattr(second, name))


def test_different_seed_changes_draws(prepared: Path, config: sim.SimulatorConfig) -> None:
    other = config.model_copy(update={"seed": config.seed + 1})
    assert not _simulate(prepared, config).keys.equals(_simulate(prepared, other).keys)


def test_transfers_never_expose_the_laundering_label(
    prepared: Path, config: sim.SimulatorConfig
) -> None:
    transfers = _simulate(prepared, config).transfers
    assert "is_laundering" not in transfers.columns
    assert transfers["tx_id"].is_unique().all()


def test_only_instant_formats_and_no_self_transfers(
    prepared: Path, config: sim.SimulatorConfig
) -> None:
    transfers = _simulate(prepared, config).transfers
    transactions = pl.read_parquet(prepared / "transactions.parquet")
    kept = transactions.join(transfers.select("tx_id"), on="tx_id")
    assert set(kept["payment_format"].cast(pl.String)) <= set(
        config.instant_transfer.payment_formats
    )
    assert not kept["is_self_transfer"].any()


def test_night_limit_between_individuals(prepared: Path, config: sim.SimulatorConfig) -> None:
    transfers = _simulate(prepared, config).transfers
    night_hop = transfers.filter(pl.col("timestamp") == datetime(2022, 9, 1, 22))
    assert night_hop["is_night"].item() is True
    assert night_hop["night_limit_applies"].item() is True  # Individual -> Individual
    assert night_hop["exceeds_night_limit"].item() is True  # 450 USD is above R$ 1,000
    corporate = transfers.filter(pl.col("timestamp") == datetime(2022, 9, 1, 21))
    assert corporate["night_limit_applies"].item() is False  # sender is a corporation


def test_keys_are_synthetic_tokens(prepared: Path, config: sim.SimulatorConfig) -> None:
    keys = _simulate(prepared, config).keys
    emails = keys.filter(pl.col("key_type") == "email")["key_value"]
    assert emails.str.ends_with("@example.invalid").all()
    others = keys.filter(pl.col("key_type") != "email")["key_value"]
    assert others.str.contains(r"^(random|tax_id|phone)-[0-9a-f]{16}$").all()
    assert set(keys["user_type"]) == {"PF", "PJ"}


def test_keys_are_registered_before_first_activity(
    prepared: Path, config: sim.SimulatorConfig
) -> None:
    keys = _simulate(prepared, config).keys
    transactions = pl.read_parquet(prepared / "transactions.parquet")
    first_seen = (
        pl.concat(
            [
                transactions.select(account_id="sender_id", t="timestamp"),
                transactions.select(account_id="receiver_id", t="timestamp"),
            ]
        )
        .group_by("account_id")
        .agg(pl.col("t").min())
    )
    joined = keys.join(first_seen, on="account_id")
    assert (joined["registered_at"] <= joined["t"]).all()
    assert (joined["t"] - joined["registered_at"] <= timedelta(days=365)).all()


def test_accepted_disputes_enter_the_mule_network(
    prepared: Path, config: sim.SimulatorConfig
) -> None:
    layer = _simulate(prepared, config)
    accepted = layer.disputes.filter(pl.col("outcome") == "accepted")
    # Only the first laundering transfer (S -> M) enters the network; M -> N is a later hop.
    assert accepted["tx_id"].to_list() == [2]
    assert accepted["scenario"].item() in config.disputes.scam_scenarios
    disputed = layer.transfers.filter(pl.col("tx_id") == 2)
    assert (
        disputed["description"].item()
        == config.disputes.scam_scenarios[accepted["scenario"].item()]
    )
    rejected = layer.disputes.filter(pl.col("outcome") == "rejected")
    assert rejected.height == 1
    filing = layer.disputes.join(layer.transfers.select("tx_id", "timestamp"), on="tx_id")
    delay = filing["filed_at"] - filing["timestamp"]
    assert (delay >= timedelta(hours=1)).all()
    assert (delay <= timedelta(hours=72)).all()


def test_dict_markings_follow_confirmations(prepared: Path, config: sim.SimulatorConfig) -> None:
    layer = _simulate(prepared, config)
    assert layer.dict_markings["marked_at"].to_list() == [
        datetime(2022, 9, 2, 21),
        datetime(2022, 9, 2, 22),
    ]
    assert layer.calibration["counts"]["dict_markings"] == 2


def test_calibration_report_compares_targets(prepared: Path, config: sim.SimulatorConfig) -> None:
    report = _simulate(prepared, config).calibration
    assert report["rejection_share"] == {"target": 0.5, "achieved": 0.5}
    assert report["accepted_disputes_per_100k"]["target"] == TARGETS.accepted_per_100k
    assert set(report["key_type_share"]) <= {"PF/random", "PF/email", "PJ/tax_id", "PJ/phone"}


def test_run_writes_every_table(prepared: Path, config: sim.SimulatorConfig) -> None:
    labels = load_config(LabelConfig, CONFIG_DIR / "labels.yaml")
    layer = sim.run(prepared, config, labels)
    written = sorted(path.name for path in (prepared / "pix_layer").iterdir())
    assert written == [
        "calibration_report.yaml",
        "pix_dict_markings.parquet",
        "pix_disputes.parquet",
        "pix_keys.parquet",
        "pix_transfers.parquet",
    ]
    assert layer.calibration["seed"] == config.seed


def test_calibration_targets_read_the_committed_figures() -> None:
    targets = sim.CalibrationTargets.from_yaml(Path("configs/calibration/bcb_public_figures.yaml"))
    assert 0 < targets.rejection_share < 1
    assert targets.accepted_per_100k > 0
    assert set(targets.key_mix) == {"PF", "PJ"}
