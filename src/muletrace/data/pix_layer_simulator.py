"""Pix-layer simulator: a seeded Brazilian instant-payment overlay on top of AMLworld.

AMLworld has no Pix keys, no dispute mechanism and no Brazilian context. This simulator adds
them without touching the AMLworld rows, so every model result can still be traced to the
original data:

* **instant transfers** — selected payment formats re-labelled as Pix, with BRL amounts, the
  night-time limit check and a synthetic free-text description;
* **Pix keys** — one synthetic key per account, with a type mix calibrated to the BCB key stock;
* **DICT fraud markings** — DICT is the Pix directory of keys and accounts, where confirmed
  fraudsters are marked; here a marking is written for every confirmed mule at confirmation time;
* **MED-style disputes** — accepted disputes on transfers that bring laundered money into a mule
  account and rejected disputes on ordinary transfers, with counts calibrated to the BCB MED
  statistics.

The simulator never generates realistic personal data: key values are opaque tokens and e-mail
keys use the reserved ``example.invalid`` domain. Every random draw comes from a child of one
seeded :class:`numpy.random.SeedSequence`, one child per component, so changing one component
does not reshuffle the others.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import polars as pl
import yaml
from pydantic import Field

from muletrace.config import StrictModel
from muletrace.data.fx import BRL
from muletrace.data.labels import LabelConfig, confirmations, mule_events

KEY_TYPE_NAMES: Final = {
    "Aleatória": "random",
    "CPF": "tax_id",
    "CNPJ": "tax_id",
    "Celular": "phone",
    "e-mail": "email",
}
_SECONDS_PER_HOUR: Final = 3600
_SECONDS_PER_DAY: Final = 86_400


class InstantTransferConfig(StrictModel):
    """Which AMLworld payment formats stand in for Pix."""

    payment_formats: tuple[str, ...] = Field(min_length=1)


class NightLimitConfig(StrictModel):
    """Night-time limit for transfers between natural persons."""

    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=0, le=23)
    limit_brl: float = Field(gt=0)


class PixKeyConfig(StrictModel):
    """Key registration parameters."""

    max_key_age_days: int = Field(gt=0)


class FilingDelayConfig(StrictModel):
    """Uniform range of hours between a transfer and its dispute."""

    min: float = Field(ge=0)
    max: float = Field(gt=0)


class DisputeConfig(StrictModel):
    """Dispute timing and illustrative scam scenarios."""

    filing_delay_hours: FilingDelayConfig
    scam_scenarios: dict[str, str] = Field(min_length=1)


class DescriptionConfig(StrictModel):
    """Synthetic transfer descriptions."""

    blank_share: float = Field(ge=0, le=1)
    everyday: tuple[str, ...] = Field(min_length=1)


class SimulatorConfig(StrictModel):
    """Configuration of the Pix-layer simulator, read from ``configs/simulator.yaml``."""

    version: str
    seed: int
    calibration_file: Path
    instant_transfer: InstantTransferConfig
    natural_person_entity_types: tuple[str, ...]
    night_limit: NightLimitConfig
    pix_keys: PixKeyConfig
    disputes: DisputeConfig
    descriptions: DescriptionConfig


@dataclass(frozen=True)
class CalibrationTargets:
    """The public aggregates the simulator is calibrated to."""

    accepted_per_100k: float
    rejection_share: float
    mean_accepted_ticket_brl: float
    key_mix: dict[str, dict[str, float]]

    @classmethod
    def from_yaml(cls, path: Path) -> CalibrationTargets:
        """Read the figures written by ``scripts/fetch_bcb_calibration.py``."""
        figures = yaml.safe_load(path.read_text(encoding="utf-8"))
        med = figures["med_disputes"]
        return cls(
            accepted_per_100k=float(med["accepted_per_100k_transfers_monthly_median"]),
            rejection_share=float(med["rejection_share"]),
            mean_accepted_ticket_brl=float(med["mean_accepted_ticket_brl"]),
            key_mix=figures["pix_key_stock"]["share_by_user_type"],
        )


@dataclass(frozen=True)
class PixLayer:
    """Every table the simulator produces, plus its calibration report."""

    transfers: pl.DataFrame
    keys: pl.DataFrame
    dict_markings: pl.DataFrame
    disputes: pl.DataFrame
    calibration: dict[str, Any]

    def write(self, output_dir: Path) -> None:
        """Write the tables as Parquet and the calibration report as YAML."""
        output_dir.mkdir(parents=True, exist_ok=True)
        for name in ("transfers", "keys", "dict_markings", "disputes"):
            frame: pl.DataFrame = getattr(self, name)
            frame.write_parquet(output_dir / f"pix_{name}.parquet", compression="zstd")
        (output_dir / "calibration_report.yaml").write_text(
            yaml.safe_dump(self.calibration, sort_keys=False), encoding="utf-8"
        )


def _tokens(rng: np.random.Generator, n: int) -> pl.Series:
    """Opaque 16-hex-digit tokens; vectorised formatting, no per-row Python loop."""
    values = rng.integers(0, np.iinfo(np.int64).max, size=n, dtype=np.int64)
    return pl.Series(np.char.mod("%016x", values), dtype=pl.String)


def _descriptions(rng: np.random.Generator, n: int, config: DescriptionConfig) -> pl.Series:
    choices = np.asarray(config.everyday, dtype=object)[rng.integers(0, len(config.everyday), n)]
    blank = rng.random(n) < config.blank_share
    return pl.Series(np.where(blank, "", choices).tolist(), dtype=pl.String)


def _instant_transfers(
    transactions: pl.DataFrame,
    natural_persons: pl.DataFrame,
    brl_per_usd: float,
    config: SimulatorConfig,
    rng: np.random.Generator,
) -> pl.DataFrame:
    night = config.night_limit
    is_natural = natural_persons.select("account_id", "is_natural_person")
    pix = (
        transactions.filter(
            pl.col("payment_format").cast(pl.String).is_in(config.instant_transfer.payment_formats)
            & ~pl.col("is_self_transfer")
        )
        .join(is_natural.rename({"account_id": "sender_id", "is_natural_person": "s"}), "sender_id")
        .join(
            is_natural.rename({"account_id": "receiver_id", "is_natural_person": "r"}),
            "receiver_id",
        )
        .with_columns(
            amount_brl=(pl.col("amount_paid_usd") * brl_per_usd).round(2),
            is_night=(pl.col("timestamp").dt.hour() >= night.start_hour)
            | (pl.col("timestamp").dt.hour() < night.end_hour),
            night_limit_applies=pl.col("s") & pl.col("r"),
        )
        .with_columns(
            exceeds_night_limit=pl.col("night_limit_applies")
            & pl.col("is_night")
            & (pl.col("amount_brl") > night.limit_brl)
        )
    )
    return pix.with_columns(description=_descriptions(rng, pix.height, config.descriptions)).select(
        "tx_id",
        "timestamp",
        "sender_id",
        "receiver_id",
        "amount_brl",
        "is_night",
        "night_limit_applies",
        "exceeds_night_limit",
        "description",
    )


def _pix_keys(
    transactions: pl.DataFrame,
    natural_persons: pl.DataFrame,
    config: SimulatorConfig,
    targets: CalibrationTargets,
    rng: np.random.Generator,
) -> pl.DataFrame:
    first_seen = (
        pl.concat(
            [
                transactions.select(account_id="sender_id", timestamp="timestamp"),
                transactions.select(account_id="receiver_id", timestamp="timestamp"),
            ]
        )
        .group_by("account_id")
        .agg(first_seen_at=pl.col("timestamp").min())
        .join(natural_persons, on="account_id")
        .sort("account_id")
    )
    frames = []
    for user_type, is_natural in (("PF", True), ("PJ", False)):
        group = first_seen.filter(pl.col("is_natural_person") == is_natural)
        mix = targets.key_mix[user_type]
        names = list(mix)
        weights = np.asarray([mix[name] for name in names])
        drawn = rng.choice(len(names), size=group.height, p=weights / weights.sum())
        frames.append(
            group.with_columns(
                user_type=pl.lit(user_type),
                key_type=pl.Series([KEY_TYPE_NAMES[names[i]] for i in drawn], dtype=pl.String),
            )
        )
    keys = pl.concat(frames).sort("account_id")
    age_seconds = rng.uniform(0, config.pix_keys.max_key_age_days * _SECONDS_PER_DAY, keys.height)
    token = _tokens(rng, keys.height)
    return keys.with_columns(
        key_value=pl.when(pl.col("key_type") == "email")
        .then(pl.lit("user-") + token + pl.lit("@example.invalid"))
        .otherwise(pl.col("key_type") + pl.lit("-") + token),
        registered_at=(
            pl.col("first_seen_at") - pl.duration(seconds=pl.lit(pl.Series(age_seconds.round())))
        ).dt.truncate("1m"),
    ).select("account_id", "user_type", "key_type", "key_value", "registered_at")


def _sample(frame: pl.DataFrame, n: int, rng: np.random.Generator) -> pl.DataFrame:
    n = min(n, frame.height)
    picked = rng.choice(frame.height, size=n, replace=False)
    return frame.select(pl.all().gather(np.sort(picked)))


def _disputes(
    *,
    transfers: pl.DataFrame,
    transactions: pl.DataFrame,
    mules: pl.DataFrame,
    config: SimulatorConfig,
    targets: CalibrationTargets,
    rng: np.random.Generator,
) -> pl.DataFrame:
    """Accepted disputes on transfers *entering* the mule network, rejected ones elsewhere."""
    labelled = transfers.join(transactions.select("tx_id", "is_laundering"), on="tx_id")
    sender_mule = mules.select(sender_id="account_id", sender_became_mule_at="became_mule_at")
    receiver_mule = mules.select(receiver_id="account_id", receiver_is_mule=pl.lit(value=True))
    labelled = labelled.join(sender_mule, on="sender_id", how="left").join(
        receiver_mule, on="receiver_id", how="left"
    )
    entering = labelled.filter(
        pl.col("is_laundering")
        & pl.col("receiver_is_mule").fill_null(value=False)
        & (
            pl.col("sender_became_mule_at").is_null()
            | (pl.col("sender_became_mule_at") > pl.col("timestamp"))
        )
    )
    ordinary = labelled.filter(~pl.col("is_laundering") & pl.col("receiver_is_mule").is_null())

    n_accepted = round(targets.accepted_per_100k * transfers.height / 100_000)
    n_rejected = round(n_accepted * targets.rejection_share / (1 - targets.rejection_share))
    accepted = _sample(entering, n_accepted, rng)
    scenarios = list(config.disputes.scam_scenarios)
    accepted = accepted.with_columns(
        outcome=pl.lit("accepted"),
        scenario=pl.Series(
            [scenarios[i] for i in rng.integers(0, len(scenarios), accepted.height)],
            dtype=pl.String,
        ),
    )
    rejected = _sample(ordinary, n_rejected, rng).with_columns(
        outcome=pl.lit("rejected"), scenario=pl.lit("not_fraud")
    )
    disputes = pl.concat([accepted, rejected]).sort("timestamp", "tx_id")
    delay = config.disputes.filing_delay_hours
    delay_seconds = rng.uniform(delay.min, delay.max, disputes.height) * _SECONDS_PER_HOUR
    return disputes.with_row_index("dispute_id").select(
        "dispute_id",
        "tx_id",
        "receiver_id",
        "amount_brl",
        filed_at=(
            pl.col("timestamp") + pl.duration(seconds=pl.lit(pl.Series(delay_seconds.round())))
        ),
        outcome=pl.col("outcome"),
        scenario=pl.col("scenario"),
    )


def _apply_scam_descriptions(
    transfers: pl.DataFrame, disputes: pl.DataFrame, config: SimulatorConfig
) -> pl.DataFrame:
    scam_text = disputes.filter(pl.col("outcome") == "accepted").select(
        "tx_id",
        scam_description=pl.col("scenario").replace_strict(config.disputes.scam_scenarios),
    )
    return (
        transfers.join(scam_text, on="tx_id", how="left")
        .with_columns(description=pl.coalesce("scam_description", "description"))
        .drop("scam_description")
    )


def _rounded(frame: pl.DataFrame, expression: pl.Expr) -> float:
    value = frame.select(expression).item()
    return round(float(value), 2) if value is not None else 0.0


def _calibration_report(
    layer_counts: dict[str, int],
    disputes: pl.DataFrame,
    keys: pl.DataFrame,
    targets: CalibrationTargets,
) -> dict[str, Any]:
    accepted = disputes.filter(pl.col("outcome") == "accepted")
    n_pix = layer_counts["instant_transfers"]
    key_shares = (
        keys.group_by("user_type", "key_type")
        .len()
        .with_columns(share=(pl.col("len") / pl.col("len").sum().over("user_type")).round(4))
        .sort("user_type", "key_type")
    )
    return {
        "counts": layer_counts,
        "accepted_disputes_per_100k": {
            "target": targets.accepted_per_100k,
            "achieved": round(accepted.height / n_pix * 100_000, 4) if n_pix else 0.0,
        },
        "rejection_share": {
            "target": targets.rejection_share,
            "achieved": round(1 - accepted.height / disputes.height, 4) if disputes.height else 0.0,
        },
        "mean_accepted_ticket_brl": {
            "target": targets.mean_accepted_ticket_brl,
            "achieved": _rounded(accepted, pl.col("amount_brl").mean()),
            "achieved_median": _rounded(accepted, pl.col("amount_brl").median()),
            "note": "Not forced: amounts are AMLworld's own, converted to BRL.",
        },
        "key_type_share": {
            f"{row['user_type']}/{row['key_type']}": row["share"]
            for row in key_shares.iter_rows(named=True)
        },
    }


def simulate(
    *,
    transactions: pl.DataFrame,
    accounts: pl.DataFrame,
    brl_per_usd: float,
    mules: pl.DataFrame,
    config: SimulatorConfig,
    targets: CalibrationTargets,
) -> PixLayer:
    """Build the Pix layer for one dataset.

    Args:
        transactions: prepared AMLworld transactions.
        accounts: prepared accounts table (for entity types).
        brl_per_usd: the inferred ``Brazil Real`` rate.
        mules: confirmed mules with ``account_id``, ``became_mule_at`` and ``confirmed_at``.
        config: simulator configuration.
        targets: public aggregates the counts are calibrated to.
    """
    keys_rng, transfers_rng, disputes_rng = (
        np.random.default_rng(child) for child in np.random.SeedSequence(config.seed).spawn(3)
    )
    natural_persons = accounts.select(
        "account_id",
        is_natural_person=pl.col("entity_type")
        .cast(pl.String)
        .is_in(config.natural_person_entity_types),
    )
    transfers = _instant_transfers(
        transactions, natural_persons, brl_per_usd, config, transfers_rng
    )
    keys = _pix_keys(transactions, natural_persons, config, targets, keys_rng)
    disputes = _disputes(
        transfers=transfers,
        transactions=transactions,
        mules=mules,
        config=config,
        targets=targets,
        rng=disputes_rng,
    )
    transfers = _apply_scam_descriptions(transfers, disputes, config)
    dict_markings = (
        mules.join(keys.select("account_id", "key_value"), on="account_id", how="left")
        .select("account_id", "key_value", marked_at="confirmed_at")
        .sort("marked_at", "account_id")
    )
    counts = {
        "instant_transfers": transfers.height,
        "night_limit_breaches": int(transfers["exceeds_night_limit"].sum()),
        "pix_keys": keys.height,
        "dict_markings": dict_markings.height,
        "disputes": disputes.height,
    }
    calibration = {
        "simulator_version": config.version,
        "seed": config.seed,
        **_calibration_report(counts, disputes, keys, targets),
    }
    return PixLayer(transfers, keys, dict_markings, disputes, calibration)


def run(dataset_dir: Path, config: SimulatorConfig, labels: LabelConfig) -> PixLayer:
    """Simulate the Pix layer for a prepared dataset and write it to ``<dataset_dir>/pix_layer``."""
    transactions = pl.read_parquet(dataset_dir / "transactions.parquet")
    rates = pl.read_parquet(dataset_dir / "usd_rates.parquet")
    brl_per_usd = float(rates.filter(pl.col("currency") == BRL)["units_per_usd"].item())
    mules = confirmations(mule_events(transactions.lazy()), labels.confirmation_delay)
    layer = simulate(
        transactions=transactions,
        accounts=pl.read_parquet(dataset_dir / "accounts.parquet"),
        brl_per_usd=brl_per_usd,
        mules=mules,
        config=config,
        targets=CalibrationTargets.from_yaml(config.calibration_file),
    )
    layer.write(dataset_dir / "pix_layer")
    return layer
