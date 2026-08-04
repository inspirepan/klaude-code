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
        assert "Pick a session and attach" in result.output

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

        async def _run_attach(session_id: str, *, peek: bool = False) -> None:
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

    def test_resume_falls_back_to_current_main_model_when_session_model_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import klaude_code.config as config_module
        import klaude_code.log as log_module
        import klaude_code.session as session_module
        import klaude_code.tui.command.model_picker as model_picker_module
        import klaude_code.tui.runner as tui_runner
        from klaude_code.cli import main as cli_main

        captured: dict[str, object] = {}
        model_response: list[tuple[int, object]] = [(200, {"ok": True})]

        class _FakeConfig:
            main_model = "gpt@openai"

            def resolve_model_location_prefer_available(self, model_name: str) -> tuple[str, str] | None:
                assert model_name == "opus@anthropic"
                return None

            def diagnose_model(self, model_name: str) -> SimpleNamespace:
                from klaude_code.config import ModelAvailability

                assert model_name == "gpt@openai"
                return SimpleNamespace(availability=ModelAvailability.AVAILABLE, detail="", suggestions=[])

        async def _run_attach(session_id: str, *, peek: bool = False) -> None:
            captured["attached_session_id"] = session_id
            captured["peek"] = peek

        def _request(method: str, path: str, **kwargs: object) -> tuple[int, object]:
            captured["model_request"] = (method, path, kwargs.get("json_body"))
            return model_response[-1]

        def _prepare_debug_logging(_debug: bool) -> tuple[bool, Path | None]:
            return False, None

        def _select_model_interactive(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("model picker should not open when main_model fallback exists")

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
        monkeypatch.setattr(config_module, "load_config", lambda: cast(object, _FakeConfig()))
        monkeypatch.setattr(session_module.Session, "exists", staticmethod(lambda *_args, **_kwargs: True))
        monkeypatch.setattr(
            session_module.Session,
            "load_meta",
            staticmethod(
                lambda *_args, **_kwargs: SimpleNamespace(model_config_name="opus@anthropic", model_name=None)
            ),
        )

        cli_main.main_callback(
            ctx=cast(typer.Context, SimpleNamespace(invoked_subcommand=None)),
            model=None,
            continue_=False,
            resume=False,
            resume_by_id="session-1",
            select_model=False,
            debug=False,
            vanilla=False,
            version=False,
        )

        assert captured["attached_session_id"] == "session-1"
        method, path, body = cast(tuple[str, str, dict[str, object]], captured["model_request"])
        assert (method, path) == ("PUT", "/api/sessions/session-1/model/config")
        assert body == {"model_name": "gpt@openai"}

        model_response.append((409, {"detail": "session is active"}))
        captured.pop("attached_session_id")
        with pytest.raises(typer.Exit) as exc_info:
            cli_main.main_callback(
                ctx=cast(typer.Context, SimpleNamespace(invoked_subcommand=None)),
                model=None,
                continue_=False,
                resume=False,
                resume_by_id="session-1",
                select_model=False,
                debug=False,
                vanilla=False,
                version=False,
            )
        assert exc_info.value.exit_code == 1
        assert "attached_session_id" not in captured

    def test_resume_prefers_unique_model_id_match_before_main_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import klaude_code.config as config_module
        import klaude_code.log as log_module
        import klaude_code.session as session_module
        import klaude_code.tui.command.model_picker as model_picker_module
        import klaude_code.tui.runner as tui_runner
        from klaude_code.cli import main as cli_main

        captured: dict[str, object] = {}

        class _FakeConfig:
            main_model = "fallback@openai"

            def resolve_model_location_prefer_available(self, model_name: str) -> tuple[str, str] | None:
                assert model_name == "opus@anthropic"
                return None

            def iter_model_entries(self, *, only_available: bool, include_disabled: bool) -> list[object]:
                assert only_available is True
                assert include_disabled is False
                return [SimpleNamespace(selector="sonnet@openrouter", model_id="claude-sonnet-4")]

        async def _run_attach(session_id: str, *, peek: bool = False) -> None:
            captured["attached_session_id"] = session_id
            captured["peek"] = peek

        def _request(method: str, path: str, **kwargs: object) -> tuple[int, object]:
            captured["model_request"] = (method, path, kwargs.get("json_body"))
            return 200, {"ok": True}

        def _prepare_debug_logging(_debug: bool) -> tuple[bool, Path | None]:
            return False, None

        def _select_model_interactive(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("model picker should not open when a resume fallback exists")

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
        monkeypatch.setattr(config_module, "load_config", lambda: cast(object, _FakeConfig()))
        monkeypatch.setattr(session_module.Session, "exists", staticmethod(lambda *_args, **_kwargs: True))
        monkeypatch.setattr(
            session_module.Session,
            "load_meta",
            staticmethod(
                lambda *_args, **_kwargs: SimpleNamespace(
                    model_config_name="opus@anthropic", model_name=" claude-sonnet-4 "
                )
            ),
        )

        cli_main.main_callback(
            ctx=cast(typer.Context, SimpleNamespace(invoked_subcommand=None)),
            model=None,
            continue_=False,
            resume=False,
            resume_by_id="session-1",
            select_model=False,
            debug=False,
            vanilla=False,
            version=False,
        )

        assert captured["attached_session_id"] == "session-1"
        method, path, body = cast(tuple[str, str, dict[str, object]], captured["model_request"])
        assert (method, path) == ("PUT", "/api/sessions/session-1/model/config")
        assert body == {"model_name": "sonnet@openrouter"}
