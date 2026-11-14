from datetime import datetime

import numpy as np
import yaml

from muletrace.serialization import to_builtin


def test_nested_numpy_values_become_plain_types() -> None:
    tree = {
        "a": np.float64(0.5),
        "b": (np.int32(3), [np.bool_(True)]),
        "c": np.arange(2),
        4: datetime(2022, 9, 1),
    }
    plain = to_builtin(tree)
    assert plain == {"a": 0.5, "b": [3, [True]], "c": [0, 1], "4": "2022-09-01T00:00:00"}
    assert yaml.safe_load(yaml.safe_dump(plain)) == plain
