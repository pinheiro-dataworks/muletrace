"""Feature configuration, read from ``configs/features.yaml``."""

from __future__ import annotations

from datetime import timedelta

from pydantic import Field

from muletrace.config import StrictModel


class NightWindow(StrictModel):
    """Hours that count as night time (the window wraps around midnight)."""

    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=0, le=23)


class StructuringConfig(StrictModel):
    """Round-amount and just-below-threshold heuristics."""

    round_amount_unit: float = Field(gt=0)
    threshold_usd: float = Field(gt=0)
    just_below_share: float = Field(gt=0, lt=1)


class GraphConfig(StrictModel):
    """PageRank parameters."""

    pagerank_damping: float = Field(gt=0, lt=1)
    pagerank_max_iterations: int = Field(gt=0)
    pagerank_tolerance: float = Field(gt=0)


class FeatureConfig(StrictModel):
    """All point-in-time feature parameters."""

    windows_hours: tuple[int, ...] = Field(min_length=1)
    detail_window_hours: int = Field(gt=0)
    night: NightWindow
    structuring: StructuringConfig
    graph: GraphConfig

    @property
    def windows(self) -> tuple[timedelta, ...]:
        """Trailing aggregate windows."""
        return tuple(timedelta(hours=hours) for hours in self.windows_hours)

    @property
    def detail_window(self) -> timedelta:
        """Window for the behavioural detail features."""
        return timedelta(hours=self.detail_window_hours)
