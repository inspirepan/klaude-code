import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from klaude_code.config import config_revision
from klaude_code.server.routes.server import router


def test_model_catalog_filters_and_reloads_config(isolated_home: Path) -> None:
    config_path = isolated_home / ".klaude" / "klaude-config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    providers = [
        {
            "provider_name": "catalog-test",
            "protocol": "openai",
            "api_key": "test-only-key",
            "model_list": [
                {"model_name": "visible", "model_id": "upstream", "model_alias": ["alias"], "effort": "high"},
                {"model_name": "disabled", "disabled": True},
            ],
        },
        {
            "provider_name": "catalog-disabled",
            "protocol": "openai",
            "api_key": "test-only-key",
            "disabled": True,
            "model_list": [{"model_name": "hidden"}],
        },
        {
            "provider_name": "catalog-unavailable",
            "protocol": "openai",
            "api_key": "${CATALOG_TEST_MISSING_KEY}",
            "model_list": [{"model_name": "unavailable"}],
        },
    ]
    config_path.write_text(json.dumps({"provider_list": providers}), encoding="utf-8")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/server/models")
        assert response.status_code == 200
        first = response.json()
        assert first == {
            "models": [
                {
                    "selector": "visible@catalog-test",
                    "model_name": "visible",
                    "provider": "catalog-test",
                    "model_id": "upstream",
                    "model_alias": ["alias"],
                    "params": ["effort high"],
                }
            ],
            "revision": config_revision(),
        }

        providers[0]["model_list"] = [{"model_name": "updated", "model_id": "new-upstream"}]
        config_path.write_text(json.dumps({"provider_list": providers}), encoding="utf-8")
        second = client.get("/api/server/models").json()
        assert [model["selector"] for model in second["models"]] == ["updated@catalog-test"]
        assert second["revision"] > first["revision"]
        assert second["revision"] == config_revision()
