"""Convert results to plain Python types before writing YAML or JSON reports."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import numpy as np


def _scalar(value: Any) -> Any:  # noqa: ANN401 - any leaf of a report tree
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def to_builtin(value: Any) -> Any:  # noqa: ANN401 - accepts and returns arbitrary report trees
    """Recursively turn NumPy scalars and arrays, tuples and datetimes into plain types."""
    if isinstance(value, Mapping):
        return {str(key): to_builtin(item) for key, item in value.items()}
    if isinstance(value, list | tuple | np.ndarray):
        items = value.tolist() if isinstance(value, np.ndarray) else value
        return [to_builtin(item) for item in items]
    return _scalar(value)
