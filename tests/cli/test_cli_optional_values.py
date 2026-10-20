from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer
from typer.testing import CliRunner


class TestCliOptionalValues:
    def test_help_hides_legacy_flags(self):
        from klaude_code.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--select-model" not in result.output
        assert "--resume-by-id" not in result.output
        assert "--model-select" not in result.output
        assert "Attach to the latest session in this directory" in result.output
        assert "Open the agents panel" in result.output

    def test_model_without_value_triggers_interactive_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        from klaude_code.cli.main import app

        def _should_not_run(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("interactive runtime should not start in a non-TTY test")

        monkeypatch.setattr("klaude_code.cli.main.asyncio.run", _should_not_run)

        runner = CliRunner()
        result = runner.invoke(app, ["--model"])

        assert result.exit_code == 2
        assert "requires a TTY" in result.output

    def test_model_value_becomes_initial_search_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import klaude_code.tui.command.model_picker as model_picker_module
        import klaude_code.tui.runner as tui_runner
        from klaude_code.cli import main as cli_main
        from klaude_code.tui.command.model_picker import ModelSelectResult, ModelSelectStatus

        captured: dict[str, object] = {}

        def _select_model_interactive(
            keywords: list[str] | None = None,
            initial_search_text: str | None = None,
        ) -> ModelSelectResult:
            captured["keywords"] = keywords
            captured["initial_search_text"] = initial_search_text
            return ModelSelectResult(status=ModelSelectStatus.SELECTED, model="picked-model")

        async def _run_attach(session_id: str, *, peek: bool = False, upgrade_notice: object = None) -> None:
            del upgrade_notice
            captured["attached_session_id"] = session_id
            captured["peek"] = peek

        def _prepare_debug_logging(_debug: bool) -> tuple[bool, Path | None]:
            return False, None

        def _request(method: str, path: str, **kwargs: object) -> tuple[int, object]:
            captured["create_request"] = (method, path, kwargs.get("json_body"))
            return 200, {"session_id": "created-session"}

        monkeypatch.setattr(model_picker_module, "select_model_interactive", _select_model_interactive)
        monkeypatch.setattr(tui_runner, "run_attach", _run_attach)
        monkeypatch.setattr(cli_main, "prepare_debug_logging", _prepare_debug_logging)
        monkeypatch.setattr("klaude_code.cli.uds_client.ensure_server_running", lambda **_kwargs: None)
        monkeypatch.setattr("klaude_code.cli.uds_client.request", _request)
        monkeypatch.setattr("klaude_code.tui.terminal.title.update_terminal_title", lambda: None)
        monkeypatch.setattr(cli_main.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr(cli_main.sys, "stdout", SimpleNamespace(isatty=lambda: True))

        cli_main.main_callback(
            ctx=cast(typer.Context, SimpleNamespace(invoked_subcommand=None)),
            model=" sonnet ",
            continue_=False,
            resume=False,
            resume_by_id=None,
            select_model=False,
            debug=False,
            vanilla=False,
            version=False,
        )

        assert captured["keywords"] is None
        assert captured["initial_search_text"] == "sonnet"
        method, path, json_body = cast(tuple[str, str, dict[str, object]], captured["create_request"])
        assert (method, path) == ("POST", "/api/sessions")
        assert json_body["model"] == "picked-model"
        assert captured["attached_session_id"] == "created-session"

    @pytest.mark.parametrize("session_state", ["idle", "running"])
    def test_continue_attaches_without_configuring_model(
        self, monkeypatch: pytest.MonkeyPatch, session_state: str
    ) -> None:
        import klaude_code.config as config_module
        import klaude_code.log as log_module
        import klaude_code.session as session_module
        import klaude_code.tui.command.model_picker as model_picker_module
        import klaude_code.tui.runner as tui_runner
        from klaude_code.cli import main as cli_main

        captured: dict[str, object] = {}
        requests: list[tuple[str, str]] = []

        async def _run_attach(session_id: str, *, peek: bool = False, upgrade_notice: object = None) -> None:
            del upgrade_notice
            captured["attached_session_id"] = session_id
            captured["peek"] = peek

        def _request(method: str, path: str, **kwargs: object) -> tuple[int, object]:
            requests.append((method, path))
            if (method, path) == ("GET", "/api/web/sessions/session-1/meta"):
                return 200, {"loaded": True, "state": session_state}
            assert (method, path) == ("PUT", "/api/sessions/session-1/model/config")
            return 409, {"detail": "session is active"}

        def _prepare_debug_logging(_debug: bool) -> tuple[bool, Path | None]:
            return False, None

        def _select_model_interactive(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("resuming should not open the model picker")

        def _load_config() -> None:
            raise AssertionError("resuming should not resolve a model from local config")

        def _noop_log(*_args: object, **_kwargs: object) -> None:
            return None

        def _stdout_write(_text: str) -> None:
            return None

        monkeypatch.setattr(tui_runner, "run_attach", _run_attach)
        monkeypatch.setattr(cli_main, "prepare_debug_logging", _prepare_debug_logging)
        monkeypatch.setattr("klaude_code.cli.uds_client.ensure_server_running", lambda **_kwargs: None)
        monkeypatch.setattr("klaude_code.cli.uds_client.request", _request)
        monkeypatch.setattr(model_picker_module, "select_model_interactive", _select_model_interactive)
        monkeypatch.setattr("klaude_code.tui.terminal.title.update_terminal_title", lambda: None)
        monkeypatch.setattr(log_module, "log", _noop_log)
        monkeypatch.setattr(cli_main.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr(cli_main.sys, "stdout", SimpleNamespace(isatty=lambda: True, write=_stdout_write))
        monkeypatch.setattr(config_module, "load_config", _load_config)
        monkeypatch.setattr(session_module.Session, "exists", staticmethod(lambda *_args, **_kwargs: True))
        monkeypatch.setattr(
            session_module.Session, "most_recent_session_id", staticmethod(lambda **_kwargs: "session-1")
        )

        cli_main.main_callback(
            ctx=cast(typer.Context, SimpleNamespace(invoked_subcommand=None)),
            model=None,
            continue_=True,
            resume=False,
            resume_by_id=None,
            select_model=False,
            debug=False,
            vanilla=False,
            version=False,
        )

        assert captured["attached_session_id"] == "session-1"
        assert requests == [("GET", "/api/web/sessions/session-1/meta")]

    @pytest.mark.parametrize("model_status", [200, 409])
    @pytest.mark.parametrize("select_model", [False, True])
    def test_continue_with_explicit_model_configures_before_attach(
        self, monkeypatch: pytest.MonkeyPatch, model_status: int, select_model: bool
    ) -> None:
        import klaude_code.log as log_module
        import klaude_code.session as session_module
        import klaude_code.tui.command.model_picker as model_picker_module
        import klaude_code.tui.runner as tui_runner
        from klaude_code.cli import main as cli_main
        from klaude_code.tui.command.model_picker import ModelSelectResult, ModelSelectStatus

        captured: dict[str, object] = {}

        async def _run_attach(session_id: str, *, peek: bool = False, upgrade_notice: object = None) -> None:
            del upgrade_notice
            captured["attached_session_id"] = session_id
            captured["peek"] = peek

        def _request(method: str, path: str, **kwargs: object) -> tuple[int, object]:
            assert (method, path) == ("PUT", "/api/sessions/session-1/model/config")
            captured["model_request"] = (method, path, kwargs.get("json_body"))
            assert "attached_session_id" not in captured
            return model_status, {"ok": True} if model_status == 200 else {"detail": "session is active"}

        def _prepare_debug_logging(_debug: bool) -> tuple[bool, Path | None]:
            return False, None

        def _select_model_interactive(*_args: object, **_kwargs: object) -> ModelSelectResult:
            return ModelSelectResult(status=ModelSelectStatus.SELECTED, model="sonnet@openrouter")

        def _noop_log(*_args: object, **_kwargs: object) -> None:
            return None

        def _stdout_write(_text: str) -> None:
            return None

        monkeypatch.setattr(tui_runner, "run_attach", _run_attach)
        monkeypatch.setattr(cli_main, "prepare_debug_logging", _prepare_debug_logging)
        monkeypatch.setattr("klaude_code.cli.uds_client.ensure_server_running", lambda **_kwargs: None)
        monkeypatch.setattr("klaude_code.cli.uds_client.request", _request)
        monkeypatch.setattr(model_picker_module, "select_model_interactive", _select_model_interactive)
        monkeypatch.setattr("klaude_code.tui.terminal.title.update_terminal_title", lambda: None)
        monkeypatch.setattr(log_module, "log", _noop_log)
        monkeypatch.setattr(cli_main.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr(cli_main.sys, "stdout", SimpleNamespace(isatty=lambda: True, write=_stdout_write))
        monkeypatch.setattr(session_module.Session, "exists", staticmethod(lambda *_args, **_kwargs: True))
        monkeypatch.setattr(
            session_module.Session, "most_recent_session_id", staticmethod(lambda **_kwargs: "session-1")
        )

        def _resume() -> None:
            cli_main.main_callback(
                ctx=cast(typer.Context, SimpleNamespace(invoked_subcommand=None)),
                model=None if select_model else "sonnet",
                continue_=True,
                resume=False,
                resume_by_id=None,
                select_model=select_model,
                debug=False,
                vanilla=False,
                version=False,
            )

        if model_status == 409:
            with pytest.raises(typer.Exit) as exc_info:
                _resume()
            assert exc_info.value.exit_code == 1
            assert "attached_session_id" not in captured
        else:
            _resume()
            assert captured["attached_session_id"] == "session-1"

        method, path, body = cast(tuple[str, str, dict[str, object]], captured["model_request"])
        assert (method, path) == ("PUT", "/api/sessions/session-1/model/config")
        assert body == {"model_name": "sonnet@openrouter"}

    @pytest.mark.parametrize("model_source", ["selector", "model_id", "main_model"])
    @pytest.mark.parametrize("model_status", [200, 409])
    def test_continue_resolves_cold_session_model_before_main_model(
        self, monkeypatch: pytest.MonkeyPatch, model_source: str, model_status: int
    ) -> None:
        import klaude_code.config as config_module
        import klaude_code.log as log_module
        import klaude_code.session as session_module
        import klaude_code.tui.runner as tui_runner
        from klaude_code.cli import main as cli_main

        captured: dict[str, object] = {}
        requests: list[tuple[str, str, object]] = []
        expected_model = {
            "selector": "opus@anthropic",
            "model_id": "sonnet@openrouter",
            "main_model": "gpt@openai",
        }[model_source]

        class _FakeConfig:
            main_model = "gpt@openai"

            def resolve_model_location_prefer_available(self, model_name: str) -> tuple[str, str] | None:
                assert model_name == "opus@anthropic"
                return ("anthropic", "opus") if model_source == "selector" else None

            def iter_model_entries(self, *, only_available: bool, include_disabled: bool) -> list[object]:
                assert only_available is True
                assert include_disabled is False
                assert model_source == "model_id"
                return [SimpleNamespace(selector="sonnet@openrouter", model_id="claude-sonnet-4")]

        async def _run_attach(session_id: str, *, peek: bool = False, upgrade_notice: object = None) -> None:
            assert requests[-1] == (
                "PUT",
                "/api/sessions/session-1/model/config",
                {"model_name": expected_model},
            )
            captured["attached_session_id"] = session_id

        def _request(method: str, path: str, **kwargs: object) -> tuple[int, object]:
            requests.append((method, path, kwargs.get("json_body")))
            if (method, path) == ("GET", "/api/web/sessions/session-1/meta"):
                return 200, {"loaded": False}
            assert (method, path) == ("PUT", "/api/sessions/session-1/model/config")
            assert "attached_session_id" not in captured
            return model_status, {"ok": True} if model_status == 200 else {"detail": "session is active"}

        def _select_model_interactive(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("model picker should not open when a resume fallback exists")

        monkeypatch.setattr(tui_runner, "run_attach", _run_attach)
        monkeypatch.setattr(cli_main, "prepare_debug_logging", lambda _debug: (False, None))
        monkeypatch.setattr("klaude_code.cli.uds_client.ensure_server_running", lambda **_kwargs: None)
        monkeypatch.setattr("klaude_code.cli.uds_client.request", _request)
        monkeypatch.setattr("klaude_code.tui.command.model_picker.select_model_interactive", _select_model_interactive)
        monkeypatch.setattr("klaude_code.tui.terminal.title.update_terminal_title", lambda: None)
        monkeypatch.setattr(log_module, "log", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(cli_main.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr(cli_main.sys, "stdout", SimpleNamespace(isatty=lambda: True, write=lambda _text: None))
        monkeypatch.setattr(config_module, "load_config", lambda: _FakeConfig())
        monkeypatch.setattr(session_module.Session, "exists", staticmethod(lambda *_args, **_kwargs: True))
        monkeypatch.setattr(
            session_module.Session, "most_recent_session_id", staticmethod(lambda **_kwargs: "session-1")
        )
        monkeypatch.setattr(
            session_module.Session,
            "load_meta",
            staticmethod(
                lambda *_args, **_kwargs: SimpleNamespace(
                    model_config_name=" opus@anthropic ",
                    model_name=" CLAUDE-SONNET-4 " if model_source != "main_model" else None,
                )
            ),
        )

        def _resume() -> None:
            cli_main.main_callback(
                ctx=cast(typer.Context, SimpleNamespace(invoked_subcommand=None)),
                model=None,
                continue_=True,
                resume=False,
                resume_by_id=None,
                select_model=False,
                debug=False,
                vanilla=False,
                version=False,
            )

        if model_status == 409:
            with pytest.raises(typer.Exit) as exc_info:
                _resume()
            assert exc_info.value.exit_code == 1
            assert "attached_session_id" not in captured
        else:
            _resume()
            assert captured["attached_session_id"] == "session-1"
        assert requests == [
            ("GET", "/api/web/sessions/session-1/meta", None),
            ("PUT", "/api/sessions/session-1/model/config", {"model_name": expected_model}),
        ]

    @pytest.mark.parametrize("server_running", [False, True])
    def test_cold_continue_without_main_model_saves_picker_selection_before_attach(
        self, monkeypatch: pytest.MonkeyPatch, server_running: bool
    ) -> None:
        import klaude_code.config as config_module
        import klaude_code.log as log_module
        import klaude_code.session as session_module
        import klaude_code.tui.runner as tui_runner
        from klaude_code.cli import main as cli_main
        from klaude_code.cli.uds_client import ServerNotRunningError
        from klaude_code.tui.command.model_picker import ModelSelectResult, ModelSelectStatus

        events: list[str] = []

        class _FakeConfig:
            main_model: str | None = None

            async def save(self) -> None:
                assert self.main_model == "sonnet@openrouter"
                events.append("save")

        cfg = _FakeConfig()

        def _request(method: str, path: str, **kwargs: object) -> tuple[int, object]:
            if (method, path) == ("GET", "/api/web/sessions/session-1/meta"):
                assert events == []
                events.append("meta")
                if not server_running:
                    raise ServerNotRunningError("server is not running")
                return 200, {"loaded": False}
            assert (method, path) == ("PUT", "/api/sessions/session-1/model/config")
            assert kwargs["json_body"] == {"model_name": "sonnet@openrouter"}
            events.append("configure")
            return 200, {"ok": True}

        def _select_model_interactive(*_args: object, **_kwargs: object) -> ModelSelectResult:
            assert cfg.main_model is None
            events.append("picker")
            return ModelSelectResult(status=ModelSelectStatus.SELECTED, model="sonnet@openrouter")

        async def _run_attach(session_id: str, *, peek: bool = False, upgrade_notice: object = None) -> None:
            assert session_id == "session-1"
            events.append("attach")

        monkeypatch.setattr(tui_runner, "run_attach", _run_attach)
        monkeypatch.setattr(cli_main, "prepare_debug_logging", lambda _debug: (False, None))
        monkeypatch.setattr("klaude_code.cli.uds_client.ensure_server_running", lambda: events.append("ensure_server"))
        monkeypatch.setattr("klaude_code.cli.uds_client.request", _request)
        monkeypatch.setattr("klaude_code.tui.command.model_picker.select_model_interactive", _select_model_interactive)
        monkeypatch.setattr("klaude_code.tui.terminal.title.update_terminal_title", lambda: None)
        monkeypatch.setattr(log_module, "log", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(cli_main.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr(cli_main.sys, "stdout", SimpleNamespace(isatty=lambda: True, write=lambda _text: None))
        monkeypatch.setattr(config_module, "load_config", lambda: cfg)
        monkeypatch.setattr(session_module.Session, "exists", staticmethod(lambda *_args, **_kwargs: True))
        monkeypatch.setattr(
            session_module.Session, "most_recent_session_id", staticmethod(lambda **_kwargs: "session-1")
        )
        monkeypatch.setattr(
            session_module.Session,
            "load_meta",
            staticmethod(lambda *_args, **_kwargs: SimpleNamespace(model_config_name=None, model_name=None)),
        )

        cli_main.main_callback(
            ctx=cast(typer.Context, SimpleNamespace(invoked_subcommand=None)),
            model=None,
            continue_=True,
            resume=False,
            resume_by_id=None,
            select_model=False,
            debug=False,
            vanilla=False,
            version=False,
        )

        assert cfg.main_model == "sonnet@openrouter"
        assert events == ["meta", "picker", "save", "ensure_server", "configure", "attach"]
