from datetime import datetime, timedelta

import polars as pl
import pytest

from muletrace.config import CONFIG_DIR, load_config
from muletrace.data.labels import LabelConfig, confirmations, mule_events


def _transactions() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "tx_id": [0, 1, 2, 3, 4],
            "timestamp": [
                datetime(2022, 9, 1, 10),
                datetime(2022, 9, 1, 9),
                datetime(2022, 9, 1, 9),
                datetime(2022, 9, 1, 8),
                datetime(2022, 9, 1, 7),
            ],
            "receiver_id": [7, 7, 7, 8, 9],
            "is_laundering": [True, True, True, True, False],
            "is_self_transfer": [False, False, False, True, False],
        },
        schema_overrides={"tx_id": pl.UInt32, "receiver_id": pl.UInt32},
    )


def test_first_illicit_inflow_with_deterministic_tie_break() -> None:
    events = mule_events(_transactions())
    assert events.to_dicts() == [
        {"account_id": 7, "became_mule_at": datetime(2022, 9, 1, 9), "first_illicit_tx_id": 1}
    ]


def test_self_transfers_and_clean_accounts_are_not_mules() -> None:
    assert set(mule_events(_transactions())["account_id"]) == {7}


def test_confirmation_adds_the_delay() -> None:
    confirmed = confirmations(mule_events(_transactions()), timedelta(hours=24))
    assert confirmed["confirmed_at"].item() == datetime(2022, 9, 2, 9)


def test_negative_delay_is_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        confirmations(mule_events(_transactions()), timedelta(hours=-1))


def test_label_config_matches_business_case_assumptions() -> None:
    config = load_config(LabelConfig, CONFIG_DIR / "labels.yaml")
    assert config.confirmation_delay == timedelta(hours=24)
    assert config.horizon == timedelta(hours=48)
    assert config.population_lookback == timedelta(days=7)
    assert len(config.fingerprint()) == 12
