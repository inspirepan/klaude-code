from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from rich.cells import cell_len
from rich.console import Console
from typer.testing import CliRunner

from klaude_code.cli import headless_cmd
from klaude_code.protocol.models.session_status import SessionStatus


def _row(**status: Any) -> dict[str, Any]:
    return {
        "id": "abcdef1234567890",
        "name": "fix-tests",
        "title": "修复测试 " * 20,
        "model": "test-model",
        "activity": "Bash: uv run pytest " * 10,
        "work_dir": str(Path.home() / "code/project"),
        "status": SessionStatus(**status).model_dump(mode="json"),
    }


def _attention(kind: str, code: str, source: str = "abcdef1234567890") -> dict[str, Any]:
    return {"kind": kind, "code": code, "source_session_id": source, "message": "private details"}


@pytest.mark.parametrize("width", [80, 100, 120])
def test_rich_keeps_attention_and_execution_visible_at_narrow_widths(width: int) -> None:
    row = _row(
        category="needs_you",
        execution="running",
        attention=[
            _attention("needs_input", "question"),
            _attention("needs_input", "question", "child-session"),
            _attention("error", "execution_failed"),
            _attention("paused", "user_paused"),
        ],
        owned={"active_agents": 2, "active_shells": 1},
    )
    output = io.StringIO()
    Console(file=output, width=width, color_system=None).print(headless_cmd._build_ps_rich_table([row]))  # pyright: ignore[reportPrivateUsage]
    text = output.getvalue()

    for expected in (
        "abcdef12",
        "fix-tests",
        "Needs you",
        "Input (2)",
        "Error:",
        "Paused:",
        "Running",
        "2 agents",
        "1 shells",
        "test-model",
        "~/code",
    ):
        assert expected in text
    assert "private details" not in text
    assert all(cell_len(line) <= width for line in text.splitlines())
    assert len(text.splitlines()) < 12


def test_plain_is_safe_and_does_not_promote_historical_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.cli.main import app

    row = _row(category="idle", last_turn={"id": "old-turn", "result": "failed"})
    row["name"] = "\x1b[31mfix-tests\x1b[0m\nsecond line"
    monkeypatch.setattr(headless_cmd, "_fetch_rows", lambda *_args, **_kwargs: [row])

    result = CliRunner().invoke(app, ["ps"])

    assert result.exit_code == 0
    assert "Idle" in result.output
    assert "Error" not in result.output and "failed" not in result.output
    assert "\x1b" not in result.output
    assert "fix-tests second" in result.output
    assert "~/code/project" in result.output


def test_ps_filters_tree_and_json_preserve_authoritative_status(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from klaude_code.cli.main import app

    root = _row(category="needs_you", execution="running", attention=[_attention("needs_input", "question")])
    child = {**_row(), "id": "child-session", "parent_session_id": root["id"]}
    grandchild = {**_row(), "id": "grandchild-session", "parent_session_id": child["id"]}
    calls: list[dict[str, Any]] = []

    def api(method: str, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        assert (method, path) == ("GET", "/api/headless/sessions")
        calls.append(params)
        return {"sessions": [grandchild, child, root]}

    monkeypatch.setattr(headless_cmd, "_api", api)
    result = CliRunner().invoke(
        app,
        [
            "ps",
            "one,two",
            "--tree",
            "--state",
            "needs_you",
            "--state",
            "working",
            "--group",
            "batch",
            "--dir",
            "/w",
            "--all",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {"sessions": [root, child, grandchild]}
    assert calls == [
        {
            "limit": 0,
            "targets": "one,two",
            "group": "batch",
            "dir": "/w",
            "state": ["needs_you", "working"],
            "include_archived": True,
            "include_children": True,
        }
    ]
    cells = headless_cmd._ps_table_rows([root, child, grandchild])  # pyright: ignore[reportPrivateUsage]
    assert cells[0][0].startswith("abcdef12")
    assert cells[1][0].startswith("child child-se")
    assert cells[2][0].startswith("child grandchi")


def test_ps_empty_and_watch_use_same_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.cli.main import app

    monkeypatch.setattr(headless_cmd, "_fetch_rows", lambda *_args, **_kwargs: [])
    assert CliRunner().invoke(app, ["ps"]).output.strip() == "no sessions"
    row = _row(category="working", execution="waiting_agents")
    monkeypatch.setattr(headless_cmd, "_fetch_rows", lambda *_args, **_kwargs: [row])
    seen: list[list[dict[str, Any]]] = []
    monkeypatch.setattr(headless_cmd, "_run_ps_watch", lambda fetch: seen.append(fetch()))

    assert CliRunner().invoke(app, ["ps", "--watch"]).exit_code == 0
    assert seen == [[row]]
