"""Synthetic labelled frames for model tests."""

import numpy as np
import polars as pl

from muletrace.config import CONFIG_DIR, load_config
from muletrace.models.train import TrainingConfig

TRAINING = load_config(TrainingConfig, CONFIG_DIR / "training.yaml").model_copy(
    update={"search": {"num_leaves": (4, 8)}, "max_boost_rounds": 50, "early_stopping_rounds": 10}
)
FEATURES = ["signal", "noise", "entity_type"]


def labelled_frame(n: int, seed: int) -> pl.DataFrame:
    """A frame whose label depends on ``signal`` only."""
    rng = np.random.default_rng(seed)
    signal = rng.normal(size=n)
    label = rng.random(n) < 1 / (1 + np.exp(-(3 * signal - 4)))
    return pl.DataFrame(
        {
            "signal": signal,
            "noise": rng.normal(size=n),
            "entity_type": rng.integers(0, 3, n),
            "label": label,
        }
    )
