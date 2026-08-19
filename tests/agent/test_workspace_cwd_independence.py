"""Regression tests: session work must not depend on the process CWD.

The server process hosts sessions rooted in different directories, so its CWD
is arbitrary. Every test here runs with CWD deliberately pointed at a
directory different from the session work_dir; before the workspace-path fix
these scenarios silently resolved against the process CWD.
"""

import asyncio
import json
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest

from klaude_code.agent.attachments.files import at_file_reader_attachment
from klaude_code.protocol import message
from klaude_code.session.session import Session
from klaude_code.tool import EditTool, ReadTool, WriteTool, build_todo_context
from klaude_code.tool.core.context import ToolContext
from klaude_code.workspace import WorkspaceEscapeError, resolve_workspace_path


def _arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest.fixture
def elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chdir to a directory that is NOT the session work_dir."""
    path = tmp_path / "server-cwd"
    path.mkdir()
    monkeypatch.chdir(path)
    return path


def _session_with_input(work_dir: Path, text: str) -> Session:
    session = Session(work_dir=work_dir)
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str(text)))
    return session


def _tool_context(session: Session) -> ToolContext:
    return ToolContext(
        file_tracker=session.file_tracker,
        todo_context=build_todo_context(session),
        session_id=session.id,
        work_dir=session.work_dir,
        file_change_summary=session.file_change_summary,
    )


# ---- @file attachments ----


def test_at_file_relative_path_resolves_against_work_dir(work_dir: Path, elsewhere: Path, isolated_home: Path) -> None:
    del isolated_home
    target = work_dir / "workflows" / "blog-article.md"
    target.parent.mkdir(parents=True)
    target.write_text("article body\n", encoding="utf-8")

    session = _session_with_input(work_dir, "更新一下 @workflows/blog-article.md")
    attachment = _arun(at_file_reader_attachment(session))

    assert attachment is not None
    assert "article body" in message.join_text_parts(attachment.parts)


def test_at_file_line_range_resolves_against_work_dir(work_dir: Path, elsewhere: Path, isolated_home: Path) -> None:
    del isolated_home
    target = work_dir / "notes.md"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")

    session = _session_with_input(work_dir, "see @notes.md#L2-3")
    attachment = _arun(at_file_reader_attachment(session))

    assert attachment is not None
    text = message.join_text_parts(attachment.parts)
    assert "two" in text
    assert "one" not in text


def test_at_file_relative_directory_resolves_against_work_dir(
    work_dir: Path, elsewhere: Path, isolated_home: Path
) -> None:
    del isolated_home
    (work_dir / "docs").mkdir()
    (work_dir / "docs" / "guide.md").write_text("g\n", encoding="utf-8")
    # A same-named directory in the CWD must not shadow the workspace one.
    (elsewhere / "docs").mkdir()

    session = _session_with_input(work_dir, "list @docs")
    attachment = _arun(at_file_reader_attachment(session))

    assert attachment is not None
    assert "guide.md" in message.join_text_parts(attachment.parts)


# ---- file tools ----


def test_read_tool_relative_path_resolves_against_work_dir(work_dir: Path, elsewhere: Path) -> None:
    (work_dir / "config.txt").write_text("workspace copy\n", encoding="utf-8")
    (elsewhere / "config.txt").write_text("cwd copy\n", encoding="utf-8")

    session = Session(work_dir=work_dir)
    result = _arun(ReadTool.call(json.dumps({"file_path": "config.txt"}), _tool_context(session)))

    assert result.status == "success"
    assert "workspace copy" in (result.output_text or "")


def test_write_tool_relative_path_creates_in_work_dir(work_dir: Path, elsewhere: Path) -> None:
    session = Session(work_dir=work_dir)
    result = _arun(WriteTool.call(json.dumps({"file_path": "out/new.txt", "content": "hi"}), _tool_context(session)))

    assert result.status == "success"
    assert (work_dir / "out" / "new.txt").read_text(encoding="utf-8") == "hi"
    assert not (elsewhere / "out").exists()


def test_edit_tool_relative_path_resolves_against_work_dir(work_dir: Path, elsewhere: Path) -> None:
    (work_dir / "app.py").write_text("value = 1\n", encoding="utf-8")

    session = Session(work_dir=work_dir)
    context = _tool_context(session)
    read_result = _arun(ReadTool.call(json.dumps({"file_path": "app.py"}), context))
    assert read_result.status == "success"

    edit_result = _arun(
        EditTool.call(
            json.dumps({"file_path": "app.py", "old_string": "value = 1", "new_string": "value = 2"}),
            context,
        )
    )

    assert edit_result.status == "success"
    assert (work_dir / "app.py").read_text(encoding="utf-8") == "value = 2\n"


# ---- resolver unit tests ----


def test_resolve_workspace_path_relative_joins_work_dir(work_dir: Path, elsewhere: Path) -> None:
    assert resolve_workspace_path("a/b.txt", work_dir) == (work_dir / "a" / "b.txt").resolve()


def test_resolve_workspace_path_absolute_passes_through(work_dir: Path) -> None:
    target = work_dir / "abs.txt"
    assert resolve_workspace_path(str(target), Path("/nonexistent-base")) == target.resolve()


def test_resolve_workspace_path_expands_user(work_dir: Path, isolated_home: Path) -> None:
    assert resolve_workspace_path("~/x.txt", work_dir) == (isolated_home / "x.txt").resolve()


def test_resolve_workspace_path_strict_rejects_escape(work_dir: Path) -> None:
    with pytest.raises(WorkspaceEscapeError):
        resolve_workspace_path("../outside.txt", work_dir, strict=True)


def test_resolve_workspace_path_strict_allows_inside(work_dir: Path) -> None:
    assert resolve_workspace_path("sub/../inside.txt", work_dir, strict=True) == (work_dir / "inside.txt").resolve()
