from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from klaude_code.cli.main import app
from klaude_code.config import Config
from klaude_code.config.config import ModelConfig, ProviderConfig
from klaude_code.protocol.llm_param import LLMClientProtocol


@pytest.fixture
def model_config(monkeypatch: pytest.MonkeyPatch) -> Config:
    config = Config(
        provider_list=[
            ProviderConfig(
                provider_name="available",
                protocol=LLMClientProtocol.OPENAI,
                api_key="tinysecret",
                model_list=[
                    ModelConfig(model_name="live", model_id="upstream", effort="high"),
                    ModelConfig(model_name="disabled", model_id="off", disabled=True),
                ],
            ),
            ProviderConfig(
                provider_name="unavailable",
                protocol=LLMClientProtocol.OPENAI,
                model_list=[ModelConfig(model_name="keyless", model_id="keyless-upstream")],
            ),
        ],
        main_model="live",
        sub_agent_models={"finder": "live"},
        theme="dark",
    )
    monkeypatch.setattr("klaude_code.config.load_config", lambda: config)

    def unexpected_server() -> None:
        pytest.fail("model discovery must not start a server")

    monkeypatch.setattr("klaude_code.cli.uds_client.ensure_server_running", unexpected_server)
    return config


@pytest.mark.parametrize("show_all", [False, True])
def test_models_json_is_available_filtered_and_credential_free(model_config: Config, show_all: bool) -> None:
    del model_config
    args = ["models", "--json", *(["--all"] if show_all else [])]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "tinysecret" not in result.output
    inventory = json.loads(result.output)
    assert inventory["defaults"]["main_model"] == "live"
    models = {entry["model_name"]: entry for entry in inventory["models"]}
    assert models["live"]["selector"] == "live@available"
    assert models["live"]["parameters"]["effort"] == "high"
    assert models["live"]["available"]
    if show_all:
        assert models["disabled"]["disabled"] and not models["disabled"]["available"]
        assert not models["keyless"]["disabled"] and not models["keyless"]["available"]
    else:
        assert set(models) == {"live"}


@pytest.mark.parametrize("show_all", [False, True])
def test_models_human_output_shows_roles_without_credentials(model_config: Config, show_all: bool) -> None:
    del model_config
    result = CliRunner().invoke(app, ["models", *(["--all"] if show_all else [])])
    assert result.exit_code == 0, result.output
    assert "live" in result.output and "main" in result.output and "finder" in result.output
    assert "tinysecret" not in result.output
    assert ("disabled" in result.output) == show_all
    assert ("keyless" in result.output) == show_all


def test_models_with_no_available_models_explains_all_flag(model_config: Config) -> None:
    model_config.provider_list[0].disabled = True
    result = CliRunner().invoke(app, ["models"])
    assert result.exit_code == 0
    assert "no models available" in result.output
    assert "klaude models --all" in result.output
