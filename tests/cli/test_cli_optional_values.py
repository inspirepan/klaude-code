from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Protocol, cast

import pytest
import typer
from typer.testing import CliRunner


class _HasModel(Protocol):
    model: str


class TestCliOptionalValues:
    def test_help_hides_legacy_flags(self):
        from klaude_code.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--select-model" not in result.output
        assert "--resume-by-id" not in result.output
        assert "--model-select" not in result.output

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

        async def _run_interactive(**_kwargs: object) -> None:
            return None

        def _prepare_debug_logging(_debug: bool) -> tuple[bool, Path | None]:
            return False, None

        monkeypatch.setattr(model_picker_module, "select_model_interactive", _select_model_interactive)
        monkeypatch.setattr(tui_runner, "run_interactive", _run_interactive)
        monkeypatch.setattr(cli_main, "prepare_debug_logging", _prepare_debug_logging)
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

        assert captured == {
            "keywords": None,
            "initial_search_text": "sonnet",
        }

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

        class _FakeConfig:
            main_model = "gpt@openai"

            def resolve_model_location_prefer_available(self, model_name: str) -> tuple[str, str] | None:
                assert model_name == "opus@anthropic"
                return None

            def diagnose_model(self, model_name: str) -> SimpleNamespace:
                from klaude_code.config import ModelAvailability

                assert model_name == "gpt@openai"
                return SimpleNamespace(availability=ModelAvailability.AVAILABLE, detail="", suggestions=[])

        async def _run_interactive(**kwargs: object) -> None:
            captured.update(kwargs)
            return None

        def _prepare_debug_logging(_debug: bool) -> tuple[bool, Path | None]:
            return False, None

        def _select_model_interactive(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("model picker should not open when main_model fallback exists")

        def _noop_log(*_args: object, **_kwargs: object) -> None:
            return None

        def _stdout_write(_text: str) -> None:
            return None

        monkeypatch.setattr(tui_runner, "run_interactive", _run_interactive)
        monkeypatch.setattr(cli_main, "prepare_debug_logging", _prepare_debug_logging)
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

        assert captured["session_id"] == "session-1"
        init_config = cast(_HasModel, captured["init_config"])
        assert init_config.model == "gpt@openai"

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

        async def _run_interactive(**kwargs: object) -> None:
            captured.update(kwargs)
            return None

        def _prepare_debug_logging(_debug: bool) -> tuple[bool, Path | None]:
            return False, None

        def _select_model_interactive(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("model picker should not open when a resume fallback exists")

        def _noop_log(*_args: object, **_kwargs: object) -> None:
            return None

        def _stdout_write(_text: str) -> None:
            return None

        monkeypatch.setattr(tui_runner, "run_interactive", _run_interactive)
        monkeypatch.setattr(cli_main, "prepare_debug_logging", _prepare_debug_logging)
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

        assert captured["session_id"] == "session-1"
        init_config = cast(_HasModel, captured["init_config"])
        assert init_config.model == "sonnet@openrouter"
