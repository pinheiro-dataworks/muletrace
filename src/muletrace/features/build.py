"""Build and cache one feature snapshot per as-of time.

A snapshot is the scored population at *t* with its point-in-time features and its outcome
columns. Outcomes are kept apart from features by name, and :func:`model_features` is the only
list a model may train on:

* outcome columns — ``label``, ``label_confirmed_at``, ``already_active``,
  ``illicit_inflow_usd`` — describe the future or the ground truth and never reach a model;
* feature columns — everything returned by :func:`model_features`.

Snapshots are cached as Parquet under a key made of the dataset name, the label and feature
configuration fingerprints and :data:`FEATURE_VERSION`, so experiments reuse them and a change of
definition can never silently reuse stale features.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Final

import polars as pl

from muletrace.data.labels import LabelConfig, confirmations, mule_events
from muletrace.features.account_features import (
    account_age_hours,
    first_seen,
    flow_aggregates,
    forwarding_speed,
    inflow_details,
)
from muletrace.features.asof import illicit_inflow_in_horizon, labels_at, scored_population
from muletrace.features.config import FeatureConfig
from muletrace.features.graph_features import graph_features

logger = logging.getLogger(__name__)

# Bump when feature code changes in a way the configuration does not capture.
FEATURE_VERSION: Final = "1"

OUTCOME_COLUMNS: Final = ("label", "label_confirmed_at", "already_active", "illicit_inflow_usd")
KEY_COLUMNS: Final = ("account_id", "as_of")
GRAPH_FEATURES: Final = (
    "in_degree",
    "out_degree",
    "pagerank",
    "sender_mean_out_degree",
    "sender_mean_pagerank",
    "confirmed_mule_senders",
    "confirmed_mule_receivers",
    "senders_with_confirmed_senders",
)
_DETAIL_FEATURES: Final = (
    "night_inflow_share",
    "round_amount_inflow_share",
    "just_below_threshold_share",
    "ach_inflow_share",
    "distinct_inflow_formats",
    "cross_bank_inflow_share",
    "max_inflow_usd",
    "median_hours_to_forward",
    "forwarded_within_24h_share",
)
_FLOW_STEMS: Final = (
    "inflow_count",
    "inflow_usd",
    "distinct_senders",
    "outflow_count",
    "outflow_usd",
    "distinct_receivers",
    "pass_through_ratio",
)


def tabular_features(config: FeatureConfig) -> list[str]:
    """Account-level behaviour features, in a fixed order."""
    flows = [f"{stem}_{hours}h" for hours in config.windows_hours for stem in _FLOW_STEMS]
    return [*flows, *_DETAIL_FEATURES, "inflow_burst_ratio", "account_age_hours", "entity_type"]


def model_features(config: FeatureConfig, *, include_graph: bool) -> list[str]:
    """The feature list a model trains on: tabular, optionally followed by graph features."""
    return tabular_features(config) + (list(GRAPH_FEATURES) if include_graph else [])


def _burst_ratio(config: FeatureConfig) -> pl.Expr:
    short, long = min(config.windows_hours), max(config.windows_hours)
    recent = pl.col(f"inflow_count_{short}h")
    baseline = pl.col(f"inflow_count_{long}h") * (short / long)
    return (recent / pl.when(baseline > 0).then(baseline)).alias("inflow_burst_ratio")


def build_snapshot(
    *,
    transactions: pl.LazyFrame,
    accounts: pl.DataFrame,
    mules: pl.DataFrame,
    first_seen_table: pl.DataFrame,
    as_of: datetime,
    labels: LabelConfig,
    features: FeatureConfig,
) -> pl.DataFrame:
    """Population, outcomes and features at ``as_of``.

    Args:
        transactions: prepared transactions.
        accounts: prepared accounts (bank and entity type).
        mules: mule events with ``confirmed_at`` for the configured delay.
        first_seen_table: output of :func:`first_seen`, computed once per dataset.
        as_of: the snapshot time.
        labels: target definition.
        features: feature definition.
    """
    population = scored_population(transactions, mules, as_of, labels.population_lookback)
    outcome = labels_at(population, mules, as_of, labels.horizon).join(
        mules.select("account_id", "became_mule_at", label_confirmed_at="confirmed_at"),
        on="account_id",
        how="left",
    )
    outcome = illicit_inflow_in_horizon(transactions, outcome, as_of, labels.horizon).with_columns(
        already_active=pl.col("became_mule_at").is_not_null() & (pl.col("became_mule_at") < as_of),
        label_confirmed_at=pl.when(pl.col("label")).then(pl.col("label_confirmed_at")),
    )
    frame = outcome.drop("became_mule_at")
    for window in features.windows:
        frame = frame.join(
            flow_aggregates(transactions, as_of, window).collect(), "account_id", "left"
        )
    frame = (
        frame.join(
            inflow_details(transactions, accounts, as_of, features).collect(), "account_id", "left"
        )
        .join(
            forwarding_speed(transactions, as_of, features.detail_window).collect(),
            "account_id",
            "left",
        )
        .join(account_age_hours(first_seen_table, as_of), "account_id", "left")
        .join(
            accounts.select(
                "account_id", entity_type=pl.col("entity_type").to_physical().cast(pl.Int32)
            ),
            "account_id",
            "left",
        )
        .join(
            graph_features(
                transactions=transactions,
                confirmed=mules,
                population=population,
                as_of=as_of,
                n_nodes=accounts.height,
                config=features.graph,
            ),
            "account_id",
            "left",
        )
        .with_columns(pl.col("^(inflow|outflow|distinct)_.*_\\d+h$").fill_null(0))
        .with_columns(_burst_ratio(features))
    )
    columns = [*KEY_COLUMNS, *OUTCOME_COLUMNS, *model_features(features, include_graph=True)]
    return frame.select(columns).sort("account_id")


def cache_key(dataset: str, labels: LabelConfig, features: FeatureConfig) -> str:
    """Directory name under which a dataset's snapshots are cached."""
    raw = f"{dataset}|{labels.fingerprint()}|{features.fingerprint()}|v{FEATURE_VERSION}"
    return f"{dataset}-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def build_snapshots(
    dataset_dir: Path,
    cache_dir: Path,
    as_of_times: list[datetime],
    labels: LabelConfig,
    features: FeatureConfig,
) -> pl.DataFrame:
    """Return every requested snapshot, building only those that are not cached yet."""
    folder = cache_dir / cache_key(dataset_dir.name, labels, features)
    folder.mkdir(parents=True, exist_ok=True)
    transactions = pl.scan_parquet(dataset_dir / "transactions.parquet")
    accounts = pl.read_parquet(dataset_dir / "accounts.parquet")
    mules: pl.DataFrame | None = None
    seen: pl.DataFrame | None = None
    frames = []
    for as_of in as_of_times:
        path = folder / f"{as_of:%Y%m%dT%H%M}.parquet"
        if not path.is_file():
            if mules is None or seen is None:
                mules = confirmations(mule_events(transactions), labels.confirmation_delay)
                seen = first_seen(transactions)
            snapshot = build_snapshot(
                transactions=transactions,
                accounts=accounts,
                mules=mules,
                first_seen_table=seen,
                as_of=as_of,
                labels=labels,
                features=features,
            )
            snapshot.write_parquet(path, compression="zstd")
            logger.info("Built snapshot %s: %d accounts", as_of, snapshot.height)
        frames.append(pl.read_parquet(path))
    return pl.concat(frames)
