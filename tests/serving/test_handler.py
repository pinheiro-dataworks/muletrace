import json
from pathlib import Path

import pytest

from muletrace.serving import handler as handler_module
from muletrace.serving.feature_client import InMemoryFeatureStore
from muletrace.serving.handler import ScoringService, handler


def test_handler_responses(service: ScoringService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handler_module, "service", lambda: service)

    def call(account: str, as_of: str | None) -> dict:
        event = {"pathParameters": {"account_id": account}}
        if as_of is not None:
            event["queryStringParameters"] = {"as_of": as_of}
        return handler(event)

    ok = call("7", "2022-09-09")
    assert ok["statusCode"] == 200
    body = json.loads(ok["body"])
    assert 0 <= body["probability"] <= 0.99
    assert len(body["reasons"]) <= 3
    assert call("7", "2022-09-10")["statusCode"] == 404
    assert call("abc", "2022-09-09")["statusCode"] == 400
    assert call("7", None)["statusCode"] == 400


def test_display_probability_is_capped(service: ScoringService) -> None:
    capped = ScoringService(service.artifact, service.store, "HI-Small", probability_cap=0.0)
    result = capped.score(0, "2022-09-09")
    assert result is not None
    assert result["probability"] == 0.0
    assert result["probability_capped"] is True


def test_service_is_built_from_the_environment(
    artifact_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_DIR", str(artifact_dir))
    monkeypatch.setenv("FEATURE_TABLE", "features")
    monkeypatch.setattr(handler_module, "DynamoDBFeatureStore", lambda _: InMemoryFeatureStore())
    handler_module.service.cache_clear()
    built = handler_module.service()
    assert built.dataset == "HI-Small"
    assert built.probability_cap == 0.99
    handler_module.service.cache_clear()
