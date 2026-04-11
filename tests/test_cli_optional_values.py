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
            preferred: str | None = None,
            keywords: list[str] | None = None,
            initial_search_text: str | None = None,
        ) -> ModelSelectResult:
            captured["preferred"] = preferred
            captured["keywords"] = keywords
            captured["initial_search_text"] = initial_search_text
            return ModelSelectResult(status=ModelSelectStatus.SELECTED, model="picked-model")

        async def _run_interactive(**_kwargs: object) -> None:
            return None

        monkeypatch.setattr(model_picker_module, "select_model_interactive", _select_model_interactive)
        monkeypatch.setattr(tui_runner, "run_interactive", _run_interactive)
        monkeypatch.setattr(cli_main, "prepare_debug_logging", lambda _debug: (False, None))
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
            "preferred": None,
            "keywords": None,
            "initial_search_text": "sonnet",
        }
