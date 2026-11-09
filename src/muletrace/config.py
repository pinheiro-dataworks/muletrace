"""Typed loading of YAML configuration files.

Every stage reads its parameters from ``configs/*.yaml`` through a pydantic model, so a typo or
a wrong type fails at load time with a clear message instead of halfway through a run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

CONFIG_DIR = Path("configs")


class StrictModel(BaseModel):
    """Base for configuration models: immutable and closed to unknown keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def fingerprint(self) -> str:
        """Short, stable hash of the configuration, used to key cached artefacts."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def load_config[ModelT: StrictModel](model: type[ModelT], path: Path) -> ModelT:
    """Read ``path`` and validate it against ``model``."""
    return model.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
