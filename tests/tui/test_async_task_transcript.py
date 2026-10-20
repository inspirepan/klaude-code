import asyncio
import json
import time

import pytest

from klaude_code.protocol import events, llm_param, tools
from klaude_code.protocol.background_task import (
    BackgroundTaskResult,
    BackgroundTaskSnapshot,
    TaskReference,
    TaskResponse,
    format_task_response,
)
from klaude_code.protocol.models import SessionIdUIExtra, SubAgentState
from klaude_code.protocol.models.session_status import SessionStatus
from klaude_code.protocol.models.tool_ui import ControlUIExtra
from klaude_code.protocol.peer import PeerMessage, PeerReceipt
from klaude_code.protocol.shell_task import ShellTaskSnapshot
from klaude_code.tui import machine as machine_module
from klaude_code.tui.commands import PromptStatusLine
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.input.prompt_status_bar import PromptBottomBar

from .test_transcript_toggle import make_envelope, patch_scrollback_writes

REPORT = "## 结论\n- render_collaboration_result 已解析\n- 第二点\n- 第三点\n- 第四点"


def _agent(task_id: str, session_id: str, description: str, status: str = "running") -> BackgroundTaskSnapshot:
    return BackgroundTaskSnapshot.model_validate(
        {
            "ref": TaskReference(
                kind="agent", owner_session_id="main", task_id=task_id, run_id=task_id, session_id=session_id
            ),
            "status": status,
            "description": description,
            "agent_type": "finder",
            "started_at": 1,
            "ended_at": None if status == "running" else 2,
            "result": None if status == "running" else BackgroundTaskResult(text="", summary=REPORT),
            "delivery_id": f"task-result:{task_id}",
        }
    )


def _shell(status: str = "failed") -> BackgroundTaskSnapshot:
    shell = ShellTaskSnapshot.model_validate(
        {
            "task_id": "shell-task-0000",
            "session_id": "main",
            "command": "pytest",
            "description": "Run the suite",
            "work_dir": "/tmp",
            "status": status,
            "exit_code": 1,
            "background": True,
            "started_at": 1.0,
            "output_path": "/tmp/out",
        }
    )
    return BackgroundTaskSnapshot(
        ref=TaskReference(kind="shell", owner_session_id="main", task_id=shell.task_id, run_id=shell.task_id),
        status="failed",
        description=shell.description,
        started_at=1,
        ended_at=2,
        shell=shell,
        delivery_id="task-result:shell",
    )


def _child_shell() -> BackgroundTaskSnapshot:
    task = _shell()
    assert task.shell is not None
    return task.model_copy(
        update={
            "ref": task.ref.model_copy(update={"owner_session_id": "child-a"}),
            "shell": task.shell.model_copy(update={"session_id": "child-a"}),
        }
    )


def _welcome() -> events.WelcomeEvent:
    return events.WelcomeEvent(
        session_id="main",
        work_dir="/tmp",
        llm_config=llm_param.LLMConfigParameter(protocol=llm_param.LLMClientProtocol.OPENAI, model_id="test-model"),
    )


def _agent_call(call_id: str, description: str) -> events.ToolCallEvent:
    return events.ToolCallEvent(
        session_id="main",
        tool_call_id=call_id,
        tool_name=tools.AGENT,
        arguments=json.dumps({"type": "finder", "description": description, "prompt": "..."}),
    )


def _wait(call_id: str, task_id: str) -> list[events.Event]:
    response = TaskResponse(tasks=[_agent(task_id, "child-a", "Find the panel")], interrupted_wait=True)
    return [
        events.ToolCallEvent(
            session_id="main",
            tool_call_id=call_id,
            tool_name=tools.MANAGE_TASKS,
            arguments=json.dumps({"action": "wait", "task_id": task_id}),
        ),
        events.ToolResultEvent(
            session_id="main",
            tool_call_id=call_id,
            tool_name=tools.MANAGE_TASKS,
            status="success",
            result=format_task_response(response),
            ui_extra=ControlUIExtra(data=response.model_dump(mode="json")),
        ),
    ]


def test_compact_transcript_reports_each_background_fact_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def run() -> None:
        patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        running = _agent("task-a", "child-a", "Find the panel")
        done = _agent("task-a", "child-a", "Find the panel", "completed")
        report = TaskResponse(tasks=[done], output=REPORT)
        peer = PeerMessage(sender_session_id="child-a", sender_label="child-a", recipient="main", body="hello\nmore")
        script: list[events.Event] = [
            _welcome(),
            events.TaskStartEvent(session_id="main", model_id="test-model"),
            _agent_call("c1", "Find the panel"),
            _agent_call("c2", "Review the style"),
            events.ToolResultEvent(
                session_id="main",
                tool_call_id="c1",
                tool_name=tools.AGENT,
                status="success",
                result="Agent task_id=task-a; status=running.",
                ui_extra=SessionIdUIExtra(session_id="child-a"),
            ),
            events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[running]),
            *_wait("w1", "task-a"),
            *_wait("w2", "task-a"),
            events.ToolCallEvent(
                session_id="main",
                tool_call_id="m1",
                tool_name=tools.MESSAGE_PEER,
                arguments=json.dumps({"target": "child-a", "body": "first line\nsecond line"}),
            ),
            events.ToolResultEvent(
                session_id="main",
                tool_call_id="m1",
                tool_name=tools.MESSAGE_PEER,
                status="success",
                result=PeerReceipt(message_id="m", target="child-a", accepted=True, mode="queued").model_dump_json(),
            ),
            events.UserMessageEvent(session_id="main", source="peer_message", peer_message=peer, content="x"),
            events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[done]),
            events.UserMessageEvent(
                session_id="main",
                source="task_completion",
                content=format_task_response(report, completion_report=True),
                task_response=report,
            ),
            *(
                events.UserMessageEvent(
                    session_id="main",
                    source="task_completion",
                    content="source=background_task\n" + TaskResponse(tasks=[_shell()]).model_dump_json(),
                )
                for _ in range(2)
            ),
        ]
        try:
            for event in script:
                await display.consume_envelope(make_envelope(event))
        finally:
            await display.stop()

    asyncio.run(run())
    out = capsys.readouterr().out
    # Consecutive launches share one header; the agent type names each row.
    assert out.count("◈ Agents") == 1
    assert "↳ Finder: Find the panel" in out and "↳ Finder: Review the style" in out
    # Repeated waits on one task collapse; a still-running result prints nothing.
    assert out.count("Waiting for Find the panel") == 1
    assert "· running" not in out and "interrupted" not in out
    # Messages name the peer by its task, show one line, and hide the receipt.
    assert "✉ Message to [finder] Find the panel" in out and "│ first line" in out and "│ second line" in out
    assert "› Message from [finder] Find the panel" in out and "│ hello" in out and "queued" not in out
    # One block per finished agent, with the type, the report head, and no IDs or cost tree.
    assert out.count("Finder: Find the panel ✓") == 1
    assert "render_collaboration_result 已解析" in out and "第二点" in out and "第三点" not in out
    assert "Background task" not in out and "total cost" not in out
    assert "task-a" not in out and "child-a" not in out
    # A finished Bash task prints one tool-style row, once.
    assert out.count("› Shell") == 1 and "Run the suite · failed · exit 1" in out


def test_compact_transcript_does_not_report_a_sub_agent_shell_finish(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def run() -> None:
        patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        running = _agent("task-a", "child-a", "清理 worker")
        try:
            for event in [
                _welcome(),
                events.TaskStartEvent(session_id="main", model_id="test-model"),
                events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[running]),
                events.TaskStartEvent(
                    session_id="child-a",
                    parent_session_id="main",
                    sub_agent_state=SubAgentState(
                        sub_agent_type="general-purpose",
                        sub_agent_desc="清理 worker",
                        sub_agent_prompt="",
                    ),
                ),
                events.UserMessageEvent(
                    session_id="child-a",
                    source="task_completion",
                    content="source=background_task\n" + TaskResponse(tasks=[_child_shell()]).model_dump_json(),
                ),
                events.UserMessageEvent(session_id="main", content="next"),
            ]:
                await display.consume_envelope(make_envelope(event))
        finally:
            await display.stop()

    asyncio.run(run())
    out = capsys.readouterr().out
    # The child's shell belongs to the child transcript; no callback row and no
    # orphaned sub-agent quote line from closing a block that never printed.
    assert "› Shell" not in out and "Run the suite" not in out
    assert "▌ \n" not in out


def test_expanded_transcript_does_not_report_a_sub_agent_shell_finish(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def run() -> None:
        patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        running = _agent("task-a", "child-a", "清理 worker")
        truncated_report = (
            "source=background_task\n"
            + TaskResponse(tasks=[_child_shell()], truncated=True, next_offset=24576).model_dump_json()
            + "\nReport continues: read the rest with ManageTasks output task_id=shell-task-0000 offset=24576."
        )
        try:
            for event in [
                _welcome(),
                events.ToggleTranscriptDetailEvent(session_id="main"),
                events.TaskStartEvent(session_id="main", model_id="test-model"),
                events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[running]),
                events.TaskStartEvent(
                    session_id="child-a",
                    parent_session_id="main",
                    sub_agent_state=SubAgentState(
                        sub_agent_type="general-purpose",
                        sub_agent_desc="清理 worker",
                        sub_agent_prompt="",
                    ),
                ),
                events.UserMessageEvent(
                    session_id="child-a",
                    source="task_completion",
                    content=truncated_report,
                ),
                events.UserMessageEvent(session_id="main", content="next"),
            ]:
                await display.consume_envelope(make_envelope(event))
        finally:
            await display.stop()

    asyncio.run(run())
    out = capsys.readouterr().out
    # The child block itself is expanded; its shell report is not a parent fact,
    # even when truncation adds the continuation hint after the JSON payload.
    assert "清理 worker" in out
    assert "› Task" not in out and "› Shell" not in out
    assert "Background report" not in out and "Run the suite" not in out
    assert "Report continues" not in out


@pytest.mark.parametrize("full", [False, True])
def test_child_sourced_and_notice_content_keeps_the_quote_gutter(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], full: bool
) -> None:
    async def run() -> None:
        patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        running = _agent("task-a", "child-a", "清理 worker")
        script: list[events.Event] = [_welcome()]
        if full:
            script.append(events.ToggleTranscriptDetailEvent(session_id="main"))
        script += [
            events.TaskStartEvent(session_id="main", model_id="test-model"),
            events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[running]),
            events.TaskStartEvent(
                session_id="child-a",
                parent_session_id="main",
                sub_agent_state=SubAgentState(
                    sub_agent_type="general-purpose",
                    sub_agent_desc="清理 worker",
                    sub_agent_prompt="",
                ),
            ),
            events.UserMessageEvent(
                session_id="child-a",
                source="peer_message",
                peer_message=PeerMessage(
                    sender_session_id="main",
                    sender_label="main",
                    recipient="child-a",
                    body="coordination\nline2",
                ),
                content="x",
            ),
            events.InterruptEvent(session_id="child-a"),
            events.CompactionEndEvent(session_id="child-a", reason="threshold", summary="## compacted\n- kept things"),
            events.UserMessageEvent(session_id="main", content="next"),
        ]
        try:
            for event in script:
                await display.consume_envelope(make_envelope(event))
        finally:
            await display.stop()

    asyncio.run(run())
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert any(line.startswith("▌") and "› Message from [main]" in line for line in lines)
    assert not any(not line.startswith("▌") and "› Message from [main]" in line for line in lines)
    if full:
        assert any(line.startswith("▌") and "Interrupted by user" in line for line in lines)
        assert not any(not line.startswith("▌") and "Interrupted by user" in line for line in lines)
        assert any(line.startswith("▌") and "Context Compacted" in line for line in lines)
        assert not any(not line.startswith("▌") and "Context Compacted" in line for line in lines)
    else:
        # Compact keeps child lifecycle notices out of the transcript entirely.
        assert "Interrupted by user" not in out and "Context Compacted" not in out


def test_status_bar_keeps_main_row_above_live_tail_and_children_below(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        patch_scrollback_writes(monkeypatch)
        monkeypatch.setattr(machine_module, "_terminal_columns_cache", (time.monotonic(), 100))
        monkeypatch.setattr(machine_module, "_terminal_lines_cache", (time.monotonic(), 40))
        bar = PromptBottomBar(invalidate=lambda: None)
        updates: list[tuple[PromptStatusLine, ...]] = []

        def sink(lines: tuple[PromptStatusLine, ...], separator: str | None) -> None:
            updates.append(lines)
            bar.set_status_lines(lines, separator_text=separator)

        display = TUIDisplay(on_status_update=sink)
        display.set_progress_ui_suspended(True)
        try:
            for event in [
                _welcome(),
                events.TaskStartEvent(session_id="main", model_id="test-model"),
                events.BackgroundTasksUpdatedEvent(
                    session_id="main", tasks=[_agent("task-a", "child-a", "Find the panel")]
                ),
                events.SessionStatusEvent(
                    session_id="main",
                    status=SessionStatus.model_validate(
                        {"category": "working", "execution": "running", "owned": {"active_agents": 1}}
                    ),
                ),
                events.TaskStartEvent(
                    session_id="child-a",
                    parent_session_id="main",
                    sub_agent_state=SubAgentState(
                        sub_agent_type="finder", sub_agent_desc="Find the panel", sub_agent_prompt=""
                    ),
                ),
                events.ToolCallEvent(
                    session_id="child-a",
                    tool_call_id="r1",
                    tool_name=tools.READ,
                    arguments=json.dumps({"file_path": "src/app.py"}),
                ),
                _wait("w1", "task-a")[0],
            ]:
                await display.consume_envelope(make_envelope(event))
            display.refresh_prompt_status()
            texts = [line.text for line in updates[-1]]
            head = [line.text for line in bar._status_head_lines()]
            tail = [line.text for line in bar._status_tail_lines()]
            child_frames: set[str] = set()
            for frame in range(6):
                bar._status_spinner_frame = frame
                main_text = "".join(fragment[1] for fragment in bar._get_status_fragments())
                assert main_text == f" ↳  {texts[0]}"
                child_frames.add("".join(fragment[1] for fragment in bar._get_status_tail_fragments()))
            assert len(child_frames) == 6
        finally:
            await display.stop()
        assert "Waiting for Find the panel" in texts[0]
        assert "Finder: Find the panel · 1 tool" in texts[1]
        assert any("Reading" in text and "src/app.py" in text for text in texts)
        assert texts[-1] == " ◈  1 agent running  /tasks"
        # The live tail (thinking preview) renders between the main row and the child rows.
        assert head == texts[:1]
        assert tail == texts[1:]

    asyncio.run(run())


@pytest.mark.parametrize("tool_name", [tools.MANAGE_TASKS, tools.MANAGE_SHELL])
@pytest.mark.parametrize("model_id", ["test-model", "gemini-2.5-pro", "grok-4"])
def test_wait_status_animates_only_when_other_work_is_running(
    monkeypatch: pytest.MonkeyPatch, tool_name: str, model_id: str
) -> None:
    async def run() -> None:
        patch_scrollback_writes(monkeypatch)
        bar = PromptBottomBar(invalidate=lambda: None)
        display = TUIDisplay(on_status_update=lambda lines, _: bar.set_status_lines(lines))
        display.set_progress_ui_suspended(True)

        async def emit(event: events.Event) -> None:
            await display.consume_envelope(make_envelope(event))
            display.refresh_prompt_status()

        def assert_waiting(waiting: bool) -> None:
            assert bar._status_head_lines()[0].waiting is waiting
            frames: set[str] = set()
            for frame in range(6):
                bar._status_spinner_frame = frame
                frames.add("".join(fragment[1] for fragment in bar._get_status_fragments()))
            assert len(frames) == (1 if waiting else 6)

        try:
            await emit(_welcome())
            await emit(events.TaskStartEvent(session_id="main", model_id=model_id))
            assert_waiting(False)
            # A failed stream can leave a tool start without a result before retry.
            await emit(events.ToolCallStartEvent(session_id="main", tool_call_id="abandoned", tool_name=tools.BASH))
            await emit(events.StepStartEvent(session_id="main"))
            await emit(events.ToolCallStartEvent(session_id="main", tool_call_id="wait", tool_name=tool_name))
            await emit(
                events.ToolCallEvent(
                    session_id="main",
                    tool_call_id="wait",
                    tool_name=tool_name,
                    arguments=json.dumps({"action": "wait", "task_id": "unknown"}),
                )
            )
            assert_waiting(True)
            await emit(events.RefreshDisplayEvent(session_id="main"))
            assert_waiting(True)
            await emit(events.ToolCallStartEvent(session_id="main", tool_call_id="bash", tool_name=tools.BASH))
            assert_waiting(False)
            await emit(
                events.ToolResultEvent(
                    session_id="main",
                    tool_call_id="bash",
                    tool_name=tools.BASH,
                    result="done",
                    status="success",
                )
            )
            assert_waiting(True)
            await emit(
                events.ToolResultEvent(
                    session_id="main",
                    tool_call_id="wait",
                    tool_name=tool_name,
                    result="done",
                    status="success",
                )
            )
            assert_waiting(False)
        finally:
            await display.stop()
            bar.stop()

    asyncio.run(run())


def test_snapshot_summary_is_display_only() -> None:
    response = TaskResponse(tasks=[_agent("task-a", "child-a", "Find the panel", "completed")])
    model_text = format_task_response(response)
    assert "summary" not in model_text and "Agent: finder" in model_text
    assert "render_collaboration_result" in response.model_dump_json()


@pytest.mark.parametrize("sender", ["main", "child-a"])
@pytest.mark.parametrize("receipt_first", [False, True])
@pytest.mark.parametrize("show_call", [False, True])
def test_peer_body_folds_only_after_a_displayed_send_is_identified(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sender: str,
    receipt_first: bool,
    show_call: bool,
) -> None:
    async def run() -> None:
        writes = patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        recipient = "child-a" if sender == "main" else "main"
        body = "unique coordination body"
        peer = PeerMessage(
            id="stable-message", sender_session_id=sender, sender_label="title", recipient=recipient, body=body
        )
        receipt = events.ToolResultEvent(
            session_id=sender,
            tool_call_id="send",
            tool_name=tools.MESSAGE_PEER,
            status="success",
            result="Message queued; not proof of reading.",
            ui_extra=ControlUIExtra(data=PeerReceipt(message_id=peer.id, target=recipient).model_dump(mode="json")),
        )
        received = events.UserMessageEvent(session_id=recipient, source="peer_message", peer_message=peer, content="x")
        script: list[events.Event] = [
            _welcome(),
            events.TaskStartEvent(session_id="main"),
            events.BackgroundTasksUpdatedEvent(
                session_id="main", tasks=[_agent("task-a", "child-a", "Find the panel")]
            ),
            events.TaskStartEvent(
                session_id="child-a",
                parent_session_id="main",
                sub_agent_state=SubAgentState(
                    sub_agent_type="finder", sub_agent_desc="Find the panel", sub_agent_prompt=""
                ),
            ),
            events.ToolResultEvent(
                session_id="main",
                tool_call_id="list",
                tool_name=tools.LIST_PEERS,
                status="success",
                result=json.dumps(
                    {
                        "peers": [
                            {"session_id": "child-a", "name": "Child title", "state": "running", "work_dir": "/tmp"}
                        ]
                    }
                ),
            ),
        ]
        if show_call:
            script.append(
                events.ToolCallEvent(
                    session_id=sender,
                    tool_call_id="send",
                    tool_name=tools.MESSAGE_PEER,
                    arguments=json.dumps({"target": recipient, "body": body}),
                )
            )
        script += [receipt, received] if receipt_first else [received, receipt]
        # Identical text with another ID is a separate message, never a match.
        script.append(received.model_copy(update={"peer_message": peer.model_copy(update={"id": "another-id"})}))
        folded = show_call and receipt_first
        expected_count = int(show_call) + (0 if folded else 1) + 1

        def check_compact(output: str) -> None:
            assert output.count(body) == expected_count
            assert ("Message received from" in output) is folded
            assert "queued" not in output and "not read" not in output
            message_lines = [line for line in output.splitlines() if "Message" in line]
            if show_call or sender == "child-a":
                assert any("[finder] Find the panel" in line for line in message_lines)
            child_direction = "received from" if folded and sender == "main" else "from" if sender == "main" else "to"
            if show_call or sender == "main":
                assert any(line.startswith("▌") and f"Message {child_direction}" in line for line in message_lines)

        try:
            for event in script:
                await display.consume_envelope(make_envelope(event))
            check_compact(capsys.readouterr().out)
            await display.consume_envelope(make_envelope(events.RefreshDisplayEvent(session_id="main")))
            check_compact(writes[-1][0])
            await display.consume_envelope(make_envelope(events.ToggleTranscriptDetailEvent(session_id="main")))
            expanded = writes[-1][0]
            assert expanded.count(body) == int(show_call) + 2
            assert "transport receipt, not read" in expanded and "stable-message" in expanded
            await display.consume_envelope(make_envelope(events.ToggleTranscriptDetailEvent(session_id="main")))
            check_compact(writes[-1][0])
        finally:
            await display.stop()

    asyncio.run(run())


def test_listed_external_peer_keeps_its_title_and_received_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def run() -> None:
        patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        try:
            for event in [
                _welcome(),
                events.ToolResultEvent(
                    session_id="main",
                    tool_call_id="list",
                    tool_name=tools.LIST_PEERS,
                    status="success",
                    result=json.dumps(
                        {
                            "peers": [
                                {
                                    "session_id": "external",
                                    "name": "Other conversation",
                                    "state": "idle",
                                    "work_dir": "/tmp",
                                }
                            ]
                        }
                    ),
                ),
                events.ToolCallEvent(
                    session_id="main",
                    tool_call_id="send",
                    tool_name=tools.MESSAGE_PEER,
                    arguments=json.dumps({"target": "external", "body": "same text"}),
                ),
                events.ToolResultEvent(
                    session_id="main",
                    tool_call_id="send",
                    tool_name=tools.MESSAGE_PEER,
                    status="success",
                    result=PeerReceipt(message_id="external-id", target="external").model_dump_json(),
                ),
                events.UserMessageEvent(
                    session_id="main",
                    source="peer_message",
                    peer_message=PeerMessage(
                        id="external-id", sender_session_id="external", recipient="main", body="same text"
                    ),
                    content="x",
                ),
            ]:
                await display.consume_envelope(make_envelope(event))
        finally:
            await display.stop()

    asyncio.run(run())
    output = capsys.readouterr().out
    assert "Message to [peer] Other conversation" in output
    assert "Message from [peer] Other conversation" in output
    assert output.count("same text") == 2 and "Message received from" not in output


@pytest.mark.parametrize(
    ("target", "label"),
    [
        ("aaaa000011", "[main]"),
        ("aaaa00", "[main]"),
        ("bbbb0000", "[main]"),  # An exact name takes precedence over ID prefixes.
        ("alice", "[finder] Find the panel"),
        ("bbbb000011", "[finder] Find the panel"),
        (" BBBB00001 ", "[finder] Find the panel"),
        ("bbbb000", "bbbb000"),  # Ambiguous prefix: no asserted identity.
        ("duplicate", "duplicate"),
        ("carol", "[peer] carol"),
        ("cccc00001", "[peer] carol"),
        ("cccc0000", "another agent"),
        ("not-listed", "not-listed"),
        ("", "another agent"),
    ],
)
def test_message_targets_resolve_names_and_unique_id_prefixes(target: str, label: str) -> None:
    from rich.console import Console

    from klaude_code.tui.components.background_tasks import (
        TaskDirectory,
        render_collaboration_call,
        render_collaboration_result,
    )
    from klaude_code.tui.components.rich.theme import get_theme
    from klaude_code.tui.transcript_detail import Detail

    directory = TaskDirectory()
    directory.name_main("aaaa000011")
    directory.name_child("bbbb000011", "finder", "Find the panel")
    directory.name_child("bbbb000022", "reviewer", "Review the panel")
    peers = [
        {"session_id": session_id, "name": name, "description": "Peer title", "state": "idle", "work_dir": "/tmp"}
        for session_id, name in [
            ("aaaa000011", "bbbb0000"),
            ("bbbb000011", "alice"),
            ("bbbb000022", "duplicate"),
            ("cccc000011", "carol"),
            ("cccc000022", "duplicate"),
        ]
    ]
    render_collaboration_result(
        tools.LIST_PEERS, json.dumps({"peers": peers}), detail=Detail.COMPACT, directory=directory
    )
    console = Console(width=100, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(
        render_collaboration_call(tools.MESSAGE_PEER, json.dumps({"target": target, "body": "hello"}), directory)
    )
    assert f"Message to {label}\n" in console.export_text()


def test_long_peer_message_shows_six_lines_in_compact_and_all_when_expanded() -> None:
    from rich.console import Console

    from klaude_code.tui.components.background_tasks import render_message
    from klaude_code.tui.components.rich.theme import get_theme
    from klaude_code.tui.transcript_detail import Detail

    body = "\n".join(f"line {index}" for index in range(1, 10))

    def plain(detail: Detail) -> str:
        console = Console(width=80, record=True, force_terminal=False, theme=get_theme().app_theme)
        console.print(render_message("›", "from", "peer", body, detail=detail))
        return console.export_text()

    compact = plain(Detail.COMPACT)
    assert "line 6" in compact and "line 7" not in compact and "… 3 more lines · ctrl-o" in compact
    assert "line 9" in plain(Detail.FULL)


def test_peer_message_direction_colors_mark_border_and_body() -> None:
    from rich.console import Console
    from rich.style import Style

    from klaude_code.tui.components.background_tasks import MARK_MESSAGE, render_message
    from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
    from klaude_code.tui.components.tools._common import MARK_CALLBACK
    from klaude_code.tui.transcript_detail import Detail

    console = Console(width=80, force_terminal=False, theme=get_theme().app_theme)

    def styles(mark: str) -> tuple[set[Style | None], set[Style | None]]:
        lines = console.render_lines(render_message(mark, "to", "peer", "hello there", detail=Detail.COMPACT))
        segments = [segment for line in lines for segment in line]
        border = {segment.style for segment in segments if segment.text.strip() in {"╭", "╰", "│"}}
        body = {segment.style for segment in segments if "hello there" in segment.text}
        return border, body

    sent, received = console.get_style(ThemeKey.PEER_MESSAGE_SENT), console.get_style(ThemeKey.PEER_MESSAGE_RECEIVED)
    assert sent != received
    assert styles(MARK_MESSAGE) == ({sent}, {sent})
    assert styles(MARK_CALLBACK) == ({received}, {received})
