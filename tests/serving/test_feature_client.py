import math
from decimal import Decimal

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from muletrace.serving.feature_client import (
    DynamoDBFeatureStore,
    decode_features,
    encode_features,
)


@given(st.lists(st.one_of(st.none(), st.floats(allow_infinity=False)), min_size=1, max_size=8))
def test_encoding_round_trips_bit_for_bit(values: list[float | None]) -> None:
    names = tuple(f"f{i}" for i in range(len(values)))
    decoded = decode_features(encode_features(dict(zip(names, values, strict=True))), names)
    for original, restored in zip(values, decoded, strict=True):
        if original is None or math.isnan(original):
            assert math.isnan(restored)
        else:
            assert restored == original
            assert np.float64(restored).tobytes() == np.float64(original).tobytes()


class _FakeTable:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}

    def get_item(self, Key: dict) -> dict:  # noqa: N803 - boto3 argument name
        item = self.rows.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def batch_writer(self, overwrite_by_pkeys: list[str]) -> "_FakeTable":
        assert overwrite_by_pkeys == ["pk", "sk"]
        return self

    def __enter__(self) -> "_FakeTable":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def put_item(self, Item: dict) -> None:  # noqa: N803 - boto3 argument name
        self.rows[(Item["pk"], Item["sk"])] = Item


def test_dynamodb_store_round_trip() -> None:
    store = DynamoDBFeatureStore("unused", table=_FakeTable())
    item = {"pk": "HI-Small#1", "sk": "2022-09-09", "features": {"a": Decimal("0.1")}}
    assert store.put_many([item]) == 1
    assert store.get("HI-Small", 1, "2022-09-09") == {"a": Decimal("0.1")}
    assert store.get("HI-Small", 2, "2022-09-09") is None
