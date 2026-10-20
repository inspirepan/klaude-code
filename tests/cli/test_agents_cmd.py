from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from klaude_code.cli.agents_cmd import build_agent_inventory, build_prime_guide
from klaude_code.cli.list_model import _build_model_rows
from klaude_code.cli.main import app
from klaude_code.config import Config
from klaude_code.config.config import ModelConfig, ProviderConfig
from klaude_code.protocol import llm_param


def _config(sub_agent_models: dict[str, Any] | None = None) -> Config:
    return Config(
        provider_list=[
            ProviderConfig(
                provider_name="test-provider",
                protocol=llm_param.LLMClientProtocol.ANTHROPIC,
                api_key="test-key",
                model_list=[
                    ModelConfig(model_name="sonnet", model_id="sonnet"),
                    ModelConfig(model_name="flash", model_id="flash"),
                ],
            )
        ],
        main_model="sonnet",
        sub_agent_models={"finder": "flash"} if sub_agent_models is None else sub_agent_models,
    )


def test_agent_inventory_includes_main_and_profiles() -> None:
    rows = build_agent_inventory(_config())
    names = [row["name"] for row in rows]
    assert names[0] == "main"
    assert "finder" in names
    assert "code-reviewer" in names
    finder = next(row for row in rows if row["name"] == "finder")
    assert finder["model"] == "flash"
    assert finder["model_note"] == ""


def test_unavailable_configured_model_reports_the_fallback() -> None:
    config = _config({"finder": "flash", "code-reviewer": ["gpt-6.1-sol:max", "opus"]})

    rows = build_agent_inventory(config)
    reviewer = next(row for row in rows if row["name"] == "code-reviewer")

    # The runtime hands the child the parent's model when nothing in the configured
    # chain is available, so the inventory must report the effective model.
    assert reviewer["model"] == "sonnet"
    assert reviewer["model_note"] == "configured 'gpt-6.1-sol:max > opus' is unavailable"


def test_model_table_tags_fallback_roles_on_the_main_model() -> None:
    config = _config({"finder": "flash", "code-reviewer": ["gpt-6.1-sol:max", "opus"]})

    rows = _build_model_rows(config.provider_list[0], config)
    trailing = {alias.plain: note.plain for alias, _, note in rows}

    assert trailing["flash"] == "finder"
    assert trailing["sonnet"] == "main · code-reviewer (fallback)"


def test_model_table_attributes_roles_to_the_model_that_runs() -> None:
    """A main_model chain may start with a model only an unusable provider defines.

    The role tags belong on the row the table prints and the runtime uses, not on
    the filtered-out row of the provider that cannot serve it.
    """

    def _provider(name: str, model: str, api_key: str | None) -> ProviderConfig:
        return ProviderConfig(
            provider_name=name,
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key=api_key,
            model_list=[ModelConfig(model_name=model, model_id=model)],
        )

    config = Config(
        provider_list=[
            _provider("keyless", "gpt-6.1-sol:max", None),
            _provider("usable", "opus", "test-key"),
        ],
        main_model=["gpt-6.1-sol:max", "opus"],
        sub_agent_models={"code-reviewer": ["gone-model", "also-gone"]},
    )

    rows = _build_model_rows(config.provider_list[1], config)
    trailing = {alias.plain: note.plain for alias, _, note in rows}

    assert trailing["opus"] == "main · code-reviewer (fallback)"


def test_prime_guide_mentions_core_loop_and_inventory() -> None:
    guide = build_prime_guide(_config())
    for needle in (
        "klaude run",
        "klaude wait",
        "klaude output",
        "klaude respond",
        "--group",
        "Exit codes",
        "finder",
        "needs_you",
        "--any",
        "without checking the directory",
        "trusted directories",
    ):
        assert needle in guide, f"prime guide is missing: {needle}"


def test_agents_json_lists_sessions_without_loading_model_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    calls: list[dict[str, Any]] = []
    row = {"id": "session-1", "state": "needs_you", "status": {"category": "needs_you"}}

    def fetch(targets: list[str], group: str | None, **kwargs: Any) -> list[dict[str, Any]]:
        assert targets == [] and group is None
        calls.append(kwargs)
        return [row]

    def unexpected_config() -> None:
        pytest.fail("session snapshots do not need the model inventory")

    monkeypatch.setattr("klaude_code.cli.headless_cmd._fetch_rows", fetch)
    monkeypatch.setattr("klaude_code.cli.agents_cmd._load_config_or_exit", unexpected_config)
    result = CliRunner().invoke(app, ["agents", "--json", "--state", "needs_you", "--dir", "/workspace"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"sessions": [row]}
    assert calls == [
        {"dir_": "/workspace", "states": ["needs_you"], "include_archived": False, "include_children": False}
    ]


def test_agents_rejects_non_tty_without_starting_server(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_server() -> None:
        pytest.fail("a non-interactive panel must not start the server")

    monkeypatch.setattr("klaude_code.cli.uds_client.ensure_server_running", unexpected_server)
    result = CliRunner().invoke(app, ["agents"])
    assert result.exit_code == 2
    assert "requires a TTY" in result.output
    assert "klaude ps" in result.output


@pytest.mark.parametrize("command", ["agents", "ps"])
def test_session_directory_filter_is_resolved_in_the_client(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directories: list[str] = []

    def fetch(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        directories.append(kwargs["dir_"])
        return []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("klaude_code.cli.headless_cmd._fetch_rows", fetch)
    result = CliRunner().invoke(app, [command, "--json", "--dir", "."])
    assert result.exit_code == 0, result.output
    assert directories == [str(tmp_path.resolve())]


@pytest.mark.parametrize("args", [["--state", "running"], ["--json", "--prime"]])
def test_agents_rejects_invalid_options_without_connecting(args: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_fetch(*args: Any, **kwargs: Any) -> None:
        pytest.fail("invalid options must not connect")

    monkeypatch.setattr("klaude_code.cli.headless_cmd._fetch_rows", unexpected_fetch)
    result = CliRunner().invoke(app, ["agents", *args])
    assert result.exit_code == 2


def test_panel_callbacks_use_async_status_output_and_explicit_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import json

    import httpx

    from klaude_code.cli.agents_cmd import _run_panel
    from klaude_code.tui import agents_panel

    requests: list[httpx.Request] = []
    snapshot = {
        "id": "session-1",
        "status": {"category": "idle"},
        "work_dir": "/workspace",
        "updated_at": 10.0,
    }

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/sessions"):
            return httpx.Response(200, json={"sessions": [snapshot]})
        if request.url.path.endswith("/output"):
            return httpx.Response(200, json={"output": "a" * 20000})
        if request.url.path.endswith("/control") and json.loads(request.content) == {"action": "dismiss"}:
            return httpx.Response(409, json={"detail": "session unavailable"})
        return httpx.Response(200, json={"session_id": "session-1"})

    async def panel(**kwargs: Any) -> None:
        assert kwargs["initial_state"] == "working"
        sessions = await kwargs["fetch_sessions"]()
        assert len(sessions) == 1 and sessions[0].status.category == "idle"
        assert await kwargs["load_output"]("session-1") == "a" * 12000
        await kwargs["control_session"]("session-1", "resume")
        await kwargs["control_session"]("session-1", "interrupt")
        with pytest.raises(RuntimeError, match="session unavailable"):
            await kwargs["control_session"]("session-1", "dismiss")

    monkeypatch.setattr("klaude_code.cli.uds_client._client_env_header", lambda: None)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(handle))
    monkeypatch.setattr(agents_panel, "run_agents_panel", panel)
    assert asyncio.run(_run_panel(dir_="/workspace", state="working", show_all=False)) is None
    assert len(requests) == 5
    assert requests[0].url.params["limit"] == "0"
    assert requests[0].url.params["dir"] == "/workspace"
    assert requests[0].url.params["include_children"] == "false"
    assert requests[0].url.params["include_archived"] == "false"
    assert requests[2].method == "POST"
    assert requests[2].url.path == "/api/headless/sessions/session-1/control"
    assert json.loads(requests[2].content) == {"action": "resume"}
    assert requests[3].url.path == "/api/headless/sessions/session-1/interrupt"
