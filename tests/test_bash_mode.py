from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest

from klaude_code.core.bash_mode import run_bash_command
from klaude_code.protocol import events
from klaude_code.session.session import Session


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


def _run_and_collect_output(*, session: Session, session_id: str, command: str) -> str:
    emitted: list[events.Event] = []

    async def _emit(evt: events.Event) -> None:
        emitted.append(evt)

    arun(run_bash_command(emit_event=_emit, session=session, session_id=session_id, command=command))

    chunks = [
        evt.content
        for evt in emitted
        if isinstance(evt, events.BashCommandOutputDeltaEvent)
    ]
    return "".join(chunks)


def test_bash_mode_pwd_uses_session_work_dir_and_avoids_interactive_shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_bash = shutil.which("bash")
    if real_bash is None:
        pytest.skip("bash is required")

    fake_shell = tmp_path / "bash"
    fake_shell.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  *i*) cd / ;;\n"
        "esac\n"
        f"exec {real_bash} \"$@\"\n",
        encoding="utf-8",
    )
    fake_shell.chmod(0o755)

    monkeypatch.setenv("SHELL", str(fake_shell))

    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    session = Session.create(work_dir=work_dir)

    output = _run_and_collect_output(session=session, session_id="s1", command="pwd")

    assert str(work_dir) in output.splitlines()


def test_bash_mode_runs_basic_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    real_bash = shutil.which("bash")
    if real_bash is None:
        pytest.skip("bash is required")

    monkeypatch.setenv("SHELL", real_bash)
    session = Session.create(work_dir=Path.cwd())

    output = _run_and_collect_output(session=session, session_id="s1", command="echo klaude-bash-smoke")

    assert "klaude-bash-smoke" in output
