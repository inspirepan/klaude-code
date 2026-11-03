from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from klaude_code.cli import main as cli_main
from klaude_code.tui.command.model_picker import ModelSelectResult, ModelSelectStatus


@pytest.fixture
def interactive(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def run_local(session_id: str | None = None, **kwargs: Any) -> None:
        captured.update(session_id=session_id, **kwargs)

    monkeypatch.setattr("klaude_code.tui.runner.run_local", run_local)
    monkeypatch.setattr(cli_main, "prepare_debug_logging", lambda _debug: (False, None))
    monkeypatch.setattr(cli_main.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli_main.sys, "stdout", SimpleNamespace(isatty=lambda: True, write=lambda _: None))
    monkeypatch.setattr("klaude_code.tui.terminal.title.update_terminal_title", lambda: None)
    return captured


def invoke(**kwargs: Any) -> None:
    options: dict[str, Any] = dict(
        model=None,
        continue_=False,
        resume=False,
        resume_by_id=None,
        select_model=False,
        debug=False,
        vanilla=False,
        version=False,
    )
    options.update(kwargs)
    with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True):
        cli_main.main_callback(ctx=cast(typer.Context, SimpleNamespace(invoked_subcommand=None)), **options)


def test_help_hides_internal_flags() -> None:
    result = CliRunner().invoke(cli_main.app, ["--help"])
    assert result.exit_code == 0
    assert "--resume-by-id" not in result.output
    assert "--model-select" not in result.output


def test_model_without_value_requires_tty() -> None:
    result = CliRunner().invoke(cli_main.app, ["--model"])
    assert result.exit_code == 2
    assert "requires a TTY" in result.output


def test_model_value_becomes_picker_search(interactive, monkeypatch: pytest.MonkeyPatch) -> None:
    searches = []

    def select(**kwargs: Any) -> ModelSelectResult:
        searches.append(kwargs["initial_search_text"])
        return ModelSelectResult(status=ModelSelectStatus.SELECTED, model="picked-model")

    monkeypatch.setattr("klaude_code.tui.command.model_picker.select_model_interactive", select)
    invoke(model=" sonnet ")
    assert searches == ["sonnet"]
    assert interactive["session_id"] is None
    assert interactive["model"] == "picked-model"


@pytest.mark.parametrize("model_source", ["selector", "model_id", "main_model"])
def test_continue_resolves_local_history_model_before_default(
    interactive,
    monkeypatch: pytest.MonkeyPatch,
    model_source: str,
) -> None:
    expected = {"selector": "opus@anthropic", "model_id": "sonnet@openrouter", "main_model": "gpt@openai"}[model_source]

    class Config:
        main_model = "gpt@openai"

        def resolve_model_location_prefer_available(self, _name: str):
            return "opus", "anthropic"

        def iter_model_entries(self, **_kwargs):
            return [SimpleNamespace(selector="sonnet@openrouter", model_id="raw-sonnet")]

    monkeypatch.setattr("klaude_code.config.load_config", Config)
    monkeypatch.setattr("klaude_code.session.Session.most_recent_session_id", lambda **_kwargs: "session-1")
    monkeypatch.setattr(
        "klaude_code.session.Session.load_meta",
        lambda *_a, **_k: SimpleNamespace(
            model_config_name="opus@anthropic" if model_source == "selector" else None,
            model_name="raw-sonnet" if model_source == "model_id" else None,
        ),
    )
    invoke(continue_=True)
    assert interactive["session_id"] == "session-1"
    assert interactive["model"] == expected


def test_continue_with_explicit_model_uses_local_runtime(interactive, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("klaude_code.session.Session.most_recent_session_id", lambda **_kwargs: "session-1")
    monkeypatch.setattr(
        "klaude_code.tui.command.model_picker.select_model_interactive",
        lambda **_kwargs: ModelSelectResult(status=ModelSelectStatus.SELECTED, model="sonnet@openrouter"),
    )
    invoke(model="sonnet", continue_=True)
    assert interactive["session_id"] == "session-1"
    assert interactive["model"] == "sonnet@openrouter"


def test_picker_selection_saved_before_local_start(interactive, monkeypatch: pytest.MonkeyPatch) -> None:
    saved = []

    class Config:
        main_model = None

        async def save(self):
            saved.append(self.main_model)

    config = Config()
    monkeypatch.setattr("klaude_code.config.load_config", lambda: config)
    monkeypatch.setattr(
        "klaude_code.tui.command.model_picker.select_model_interactive",
        lambda **_kwargs: ModelSelectResult(status=ModelSelectStatus.SELECTED, model="sonnet@openrouter"),
    )
    invoke()
    assert saved == ["sonnet@openrouter"]
    assert interactive["model"] == "sonnet@openrouter"


def test_resume_by_id_uses_selected_history_directory(
    interactive, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "klaude_code.cli.history.select_history", lambda _target: SimpleNamespace(id="other", work_dir=str(tmp_path))
    )
    monkeypatch.setattr(
        "klaude_code.session.Session.load_meta",
        lambda *_a, **_k: SimpleNamespace(model_config_name=None, model_name=None),
    )
    monkeypatch.setattr("klaude_code.config.load_config", lambda: SimpleNamespace(main_model="fake"))
    invoke(resume_by_id="other")
    assert interactive["session_id"] == "other"
    assert interactive["work_dir"] == tmp_path
