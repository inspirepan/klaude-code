from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
from typer.testing import CliRunner

from klaude_code.cli import headless_cmd
from klaude_code.cli.headless_cmd import (
    EXIT_FAILED,
    EXIT_WAITING_INPUT,
    _exit_code_for_states,  # pyright: ignore[reportPrivateUsage]
    _pending_request_lines,  # pyright: ignore[reportPrivateUsage]
    _poll_until_settled,  # pyright: ignore[reportPrivateUsage]
    _short_id,  # pyright: ignore[reportPrivateUsage]
    _shorten,  # pyright: ignore[reportPrivateUsage]
    _split_targets,  # pyright: ignore[reportPrivateUsage]
    _watch_ps_rows,  # pyright: ignore[reportPrivateUsage]
)
from klaude_code.protocol import events


def _event_frame(event: events.Event, sequence: int) -> dict[str, Any]:
    event_type = events.event_type_name(event)
    return events.EventEnvelope(
        event_id=f"event-{sequence}",
        event_seq=sequence,
        session_id=event.session_id,
        event_type=event_type,
        durability=events.event_durability(event_type),
        timestamp=event.timestamp,
        event=event,
    ).model_dump(mode="json")


def test_split_targets_mixes_spaces_and_commas() -> None:
    assert _split_targets(["a3f2,9b01", "fix-tests"]) == ["a3f2", "9b01", "fix-tests"]
    assert _split_targets(["a, b ,", ""]) == ["a", "b"]


def test_exit_code_severity_order() -> None:
    assert _exit_code_for_states(["idle", "idle"]) == 0
    assert _exit_code_for_states(["idle", "waiting_input"]) == EXIT_WAITING_INPUT
    assert _exit_code_for_states(["waiting_input", "failed"]) == EXIT_FAILED


def test_waiting_input_is_settled_even_with_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {"state": "waiting_input", "pending": True}
    monkeypatch.setattr(headless_cmd, "_fetch_rows", lambda _targets, _group: [row])

    rows, timed_out = _poll_until_settled(["session"], None, timeout=0)

    assert rows == [row]
    assert timed_out is False
    assert _exit_code_for_states([rows[0]["state"]]) == EXIT_WAITING_INPUT


def test_shorten_and_short_id() -> None:
    assert _shorten("word " * 40, 20).endswith("…")
    assert len(_shorten("word " * 40, 20)) == 20
    assert _short_id("abcdef1234567890") == "abcdef12"


def test_pending_request_lines_with_options() -> None:
    lines = _pending_request_lines(
        {
            "type": "question",
            "prompt": "Which option?",
            "options": [
                {"index": 1, "label": "A", "description": "choose A"},
                {"index": 2, "label": "B", "description": ""},
            ],
        },
        target="a3f2c1",
    )
    assert lines[0] == "pending question: Which option?"
    assert lines[1] == "  1. A — choose A"
    assert lines[2] == "  2. B"
    assert lines[3] == "answer with: klaude respond a3f2c1 --option N"


def test_pending_request_lines_free_text() -> None:
    lines = _pending_request_lines({"type": "question", "prompt": "Say what?", "options": []}, target="a3f2c1")
    assert lines[-1] == "answer with: klaude respond a3f2c1 --text '...'"


def test_watch_loop_supports_finite_refreshes() -> None:
    fetched = iter([[{"id": "one"}], [{"id": "two"}]])
    updates: list[list[dict[str, Any]]] = []
    sleeps: list[float] = []

    _watch_ps_rows(
        lambda: next(fetched),
        updates.append,
        interval=0.5,
        max_refreshes=2,
        sleep=sleeps.append,
    )

    assert updates == [[{"id": "one"}], [{"id": "two"}]]
    assert sleeps == [0.5]


def test_ps_watch_and_json_are_mutually_exclusive() -> None:
    from klaude_code.cli.main import app

    result = CliRunner().invoke(app, ["ps", "--watch", "--json"])

    assert result.exit_code == 2
    assert "--watch and --json are mutually exclusive" in result.output


@pytest.mark.parametrize(
    "args, message",
    [
        (["output", "one", "two", "--follow"], "requires exactly one TARGET"),
        (["output", "one", "--follow", "--group", "batch"], "cannot be used with --group"),
        (["output", "one", "--follow", "--json"], "--follow and --json are mutually exclusive"),
        (["output", "one", "--follow", "--turns", "2"], "cannot be used with --turns or --transcript"),
        (["output", "one", "--follow", "--transcript"], "cannot be used with --turns or --transcript"),
    ],
)
def test_output_follow_rejects_incompatible_options(args: list[str], message: str) -> None:
    from klaude_code.cli.main import app

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 2
    assert message in result.output


def test_output_follow_idle_returns_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.cli.main import app

    monkeypatch.setattr(
        headless_cmd,
        "_fetch_output",
        lambda *_args, **_kwargs: {"id": "session-id", "state": "idle", "pending": False, "output": "old"},
    )

    async def fail_if_connected(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("idle follow must not connect")

    monkeypatch.setattr(headless_cmd, "_follow_output_stream", fail_if_connected)

    result = CliRunner().invoke(app, ["output", "session-id", "--follow"])

    assert result.exit_code == 0
    assert result.output == ""


def test_follow_stream_prints_each_delta_once_and_exits_on_finish(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from websockets.asyncio import client as websocket_client

    finished = False

    class FakeWebSocket:
        def __init__(self) -> None:
            self.frames: Iterator[dict[str, Any]] = iter(
                [
                    {"type": "connection_info", "session_id": "session-id"},
                    {"type": "replay_complete", "session_id": "session-id"},
                    _event_frame(events.AssistantTextDeltaEvent(session_id="session-id", content="hello "), 7),
                    _event_frame(events.AssistantTextDeltaEvent(session_id="session-id", content="hello "), 7),
                    _event_frame(events.AssistantTextDeltaEvent(session_id="session-id", content="world"), 8),
                    _event_frame(events.TaskFinishEvent(session_id="session-id", task_result="success"), 9),
                ]
            )

        async def recv(self) -> str:
            nonlocal finished
            frame = next(self.frames)
            if frame.get("event_type") == "task.finish":
                finished = True
            return json.dumps(frame)

        async def close(self) -> None:
            return None

    async def fake_connect(**_kwargs: object) -> FakeWebSocket:
        return FakeWebSocket()

    def fetch_rows(*_args: object, **_kwargs: object) -> list[dict[str, Any]]:
        return [{"id": "session-id", "state": "idle" if finished else "running", "pending": False}]

    monkeypatch.setattr(websocket_client, "unix_connect", fake_connect)
    monkeypatch.setattr(headless_cmd, "_fetch_rows", fetch_rows)
    monkeypatch.setattr(
        headless_cmd,
        "_fetch_output",
        lambda *_args, **_kwargs: {"id": "session-id", "state": "idle", "output": "hello world"},
    )

    exit_code = asyncio.run(headless_cmd._follow_output_stream("session-id", initial_output=""))  # pyright: ignore[reportPrivateUsage]

    assert exit_code == 0
    assert capsys.readouterr().out == "hello world\n"


def test_follow_stream_fills_connection_race_from_final_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from websockets.asyncio import client as websocket_client

    class FakeWebSocket:
        async def recv(self) -> str:
            return json.dumps(_event_frame(events.TaskFinishEvent(session_id="session-id", task_result="success"), 10))

        async def close(self) -> None:
            return None

    async def fake_connect(**_kwargs: object) -> FakeWebSocket:
        return FakeWebSocket()

    monkeypatch.setattr(websocket_client, "unix_connect", fake_connect)
    monkeypatch.setattr(
        headless_cmd,
        "_fetch_rows",
        lambda *_args, **_kwargs: [{"id": "session-id", "state": "idle", "pending": False}],
    )
    monkeypatch.setattr(
        headless_cmd,
        "_fetch_output",
        lambda *_args, **_kwargs: {
            "id": "session-id",
            "state": "idle",
            "pending": False,
            "output": "completed before connect",
        },
    )

    exit_code = asyncio.run(headless_cmd._follow_output_stream("session-id", initial_output="old output"))  # pyright: ignore[reportPrivateUsage]

    assert exit_code == 0
    assert capsys.readouterr().out == "completed before connect\n"


def test_headless_help_lists_watch_follow_and_approval_warning() -> None:
    from klaude_code.cli.main import app

    runner = CliRunner()
    ps_help = runner.invoke(app, ["ps", "--help"])
    output_help = runner.invoke(app, ["output", "--help"])
    run_help = runner.invoke(app, ["run", "--help"])

    assert ps_help.exit_code == 0
    assert "--watch" in ps_help.output
    assert output_help.exit_code == 0
    assert "--follow" in output_help.output
    assert run_help.exit_code == 0
    assert "approve everything; use only in trusted dirs" in run_help.output
