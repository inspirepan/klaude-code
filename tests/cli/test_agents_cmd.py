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


@pytest.mark.parametrize("peek", [False, True])
def test_panel_callbacks_use_async_status_output_and_explicit_controls(
    peek: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
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
            assert request.url.params["preview"] == "true"
            return httpx.Response(200, json={"output": "reply", "user_messages": ["input"], "user_message_count": 1})
        if request.url.path.endswith("/control") and json.loads(request.content) == {"action": "dismiss"}:
            return httpx.Response(409, json={"detail": "session unavailable"})
        return httpx.Response(200, json={"session_id": "session-1"})

    async def panel(**kwargs: Any) -> None:
        assert kwargs["initial_state"] == "working"
        assert kwargs["current_dir"] == str(Path.cwd().resolve())
        sessions = await kwargs["fetch_sessions"]()
        assert len(sessions) == 1 and sessions[0].status.category == "idle"
        preview = await kwargs["load_output"]("session-1")
        assert preview == agents_panel.AgentPanelPreview(output="reply", user_messages=["input"], user_message_count=1)
        if peek:
            assert kwargs["control_session"] is None
            return
        await kwargs["control_session"]("session-1", "resume")
        await kwargs["control_session"]("session-1", "interrupt")
        with pytest.raises(RuntimeError, match="session unavailable"):
            await kwargs["control_session"]("session-1", "dismiss")

    monkeypatch.setattr("klaude_code.cli.uds_client._client_env_header", lambda: None)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(handle))
    monkeypatch.setattr(agents_panel, "run_agents_panel", panel)
    assert asyncio.run(_run_panel(dir_="/workspace", state="working", show_all=False, peek=peek)) is None
    assert len(requests) == (2 if peek else 5)
    assert requests[0].url.params["limit"] == "0"
    assert requests[0].url.params["dir"] == "/workspace"
    assert requests[0].url.params["include_children"] == "false"
    assert requests[0].url.params["include_archived"] == "false"
    if peek:
        assert all(request.method == "GET" for request in requests)
        return
    assert requests[2].method == "POST"
    assert requests[2].url.path == "/api/headless/sessions/session-1/control"
    assert json.loads(requests[2].content) == {"action": "resume"}
    assert requests[3].url.path == "/api/headless/sessions/session-1/interrupt"


@pytest.mark.parametrize("scope", ["all", "parent", "current", "other"])
def test_panel_initial_fetch_is_exact_cwd_and_respects_directory_scope(
    scope: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    import httpx

    from klaude_code.cli.agents_cmd import _run_panel
    from klaude_code.tui import agents_panel

    cwd = tmp_path / "current"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    cwd = cwd.resolve()
    other = cwd.parent / "other"
    directory = {"all": None, "parent": str(cwd.parent), "current": str(cwd), "other": str(other)}[scope]
    rows: list[dict[str, Any]] = [
        {"id": name, "work_dir": str(path), "updated_at": 1, "status": {"category": "idle"}}
        for name, path in [("local", cwd), ("child", cwd / "child"), ("other", other)]
    ]
    requested: list[str | None] = []

    def handle(request: httpx.Request) -> httpx.Response:
        prefix = request.url.params.get("dir")
        requested.append(prefix)
        assert request.url.params["include_archived"] == "true"
        return httpx.Response(
            200,
            json={"sessions": [row for row in rows if prefix is None or Path(row["work_dir"]).is_relative_to(prefix)]},
        )

    async def panel(**kwargs: Any) -> None:
        initial = kwargs["initial_fetch_sessions"]
        if scope == "other":
            assert initial is None
        else:
            assert initial is not None
            assert [row.id for row in await initial()] == ["local"]
        full = await kwargs["fetch_sessions"]()
        expected = {
            "all": ["local", "child", "other"],
            "parent": ["local", "child", "other"],
            "current": ["local", "child"],
            "other": ["other"],
        }[scope]
        assert [row.id for row in full] == expected

    monkeypatch.setattr("klaude_code.cli.uds_client._client_env_header", lambda: None)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(handle))
    monkeypatch.setattr(agents_panel, "run_agents_panel", panel)
    asyncio.run(_run_panel(dir_=directory, state="all", show_all=True))
    assert requested == ([directory] if scope == "other" else [str(cwd), directory])


@pytest.mark.parametrize("args", [["-r"], ["--resume"], ["attach"], ["agents"], ["attach", "--peek", "--debug"]])
def test_picker_entrypoints_share_the_panel_loop(args: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("klaude_code.cli.agents_cmd.run_agents_browser", lambda **kwargs: calls.append(kwargs))
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0].get("dir_") is None
    assert bool(calls[0].get("peek")) == ("--peek" in args)
    assert bool(calls[0].get("debug")) == ("--debug" in args)


@pytest.mark.parametrize("args", [["-r", "named"], ["--resume", "named"], ["--resume=named"], ["attach", "named"]])
def test_attach_aliases_resolve_globally_without_local_config(args: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []
    attached: list[tuple[str, dict[str, Any]]] = []

    def request(method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        calls.append((method, path, kwargs))
        return 200, {"sessions": [{"id": "other-project-session", "work_dir": "/other"}]}

    monkeypatch.setattr("klaude_code.cli.uds_client.ensure_server_running", lambda: None)
    monkeypatch.setattr("klaude_code.cli.uds_client.request_with_autostart", request)
    monkeypatch.setattr("klaude_code.cli.attach_cmd.run_attach_tui", lambda id, **kwargs: attached.append((id, kwargs)))
    monkeypatch.setattr(
        "klaude_code.config.load_config", lambda: pytest.fail("attach must not load local model config")
    )
    result = CliRunner().invoke(app, [*args, "--debug"])
    assert result.exit_code == 0, result.output
    assert calls == [("GET", "/api/headless/sessions", {"params": {"targets": "named", "limit": 1}})]
    assert attached == [("other-project-session", {"peek": False, "debug": True})]


@pytest.mark.parametrize("peek", [False, True])
def test_attach_panel_preserves_peek_debug_and_returns_after_detach(
    peek: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys
    from types import SimpleNamespace

    from klaude_code.cli.attach_cmd import attach_session
    from klaude_code.tui.agents_panel import AgentsPanelResult

    selections = iter(
        [AgentsPanelResult(session_id="a", action="attach"), AgentsPanelResult(session_id="b", action="peek"), None]
    )
    attached: list[tuple[str, dict[str, Any]]] = []

    async def panel(**kwargs: Any) -> AgentsPanelResult | None:
        assert kwargs == {"dir_": None, "state": "all", "show_all": False, "peek": peek}
        return next(selections)

    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(isatty=lambda: True, write=lambda _: None, flush=lambda: None))
    monkeypatch.setattr("klaude_code.cli.agents_cmd._run_panel", panel)
    monkeypatch.setattr("klaude_code.cli.uds_client.ensure_server_running", lambda: None)
    monkeypatch.setattr("klaude_code.cli.attach_cmd.run_attach_tui", lambda id, **kwargs: attached.append((id, kwargs)))
    attach_session(peek=peek, debug=True)
    assert attached == [("a", {"peek": peek, "debug": True}), ("b", {"peek": True, "debug": True})]
