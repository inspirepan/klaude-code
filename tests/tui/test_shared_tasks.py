from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from rich.console import Console

from klaude_code.protocol import events, message, tools
from klaude_code.protocol.background_task import (
    BackgroundTaskResult,
    BackgroundTaskSnapshot,
    TaskReference,
    TaskResponse,
)
from klaude_code.protocol.models import SessionIdUIExtra, SubAgentState, TaskMetadata, TaskMetadataItem, Usage
from klaude_code.protocol.peer import PeerMessage
from klaude_code.protocol.user_interaction import AskUserQuestionRequestPayload
from klaude_code.session.session import Session
from klaude_code.tui import machine as machine_module
from klaude_code.tui.client.socket_client import SocketRuntimeClient, _local_envelope
from klaude_code.tui.command import get_command_info_list, has_background_command
from klaude_code.tui.commands import (
    AppendAssistant,
    PromptStatusLine,
    RenderNotice,
    RenderSubAgentBatchSummary,
    RenderTaskMetadata,
    RenderUserMessage,
    SpinnerStop,
)
from klaude_code.tui.components.background_tasks import (
    render_collaboration_result,
    render_sourced_message,
    render_task_response,
)
from klaude_code.tui.components.tools._dispatch import render_tool_result
from klaude_code.tui.components.tools._presentation import get_tool_call_presentation
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.machine import DisplayStateMachine
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.transcript_detail import Detail, TranscriptDetail

from .test_background_shell_status import _snapshot
from .test_transcript_rebuild import _welcome
from .test_transcript_toggle import make_envelope, patch_scrollback_writes


def task_snapshot(status: str = "running", **changes: object) -> BackgroundTaskSnapshot:
    return BackgroundTaskSnapshot.model_validate(
        {
            "ref": TaskReference(
                kind="agent", owner_session_id="main", task_id="agent-1", run_id="run", session_id="child"
            ),
            "status": status,
            "description": "inspect shared tasks",
            "started_at": 1.0,
            "delivery_id": "task-result:agent-1",
            **changes,
        }
    )


def plain(renderable: object) -> str:
    console = Console(width=160, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


@pytest.mark.parametrize("finish", ["finish", "interrupt"])
def test_background_rows_and_counts_survive_root_end_toggle_refresh_and_authoritative_removal(
    monkeypatch: pytest.MonkeyPatch, finish: str
) -> None:
    async def run() -> None:
        patch_scrollback_writes(monkeypatch)
        updates: list[tuple[PromptStatusLine, ...]] = []
        display = TUIDisplay(on_status_update=lambda lines, *_: updates.append(lines))
        display.set_progress_ui_suspended(True)

        async def emit(event: events.Event) -> None:
            await display.consume_envelope(make_envelope(event))
            display.refresh_prompt_status()

        try:
            await emit(_welcome("main"))
            await emit(events.TaskStartEvent(session_id="main"))
            await emit(
                events.TaskStartEvent(
                    session_id="child",
                    parent_session_id="main",
                    model_id="child-model",
                    sub_agent_state=SubAgentState(
                        sub_agent_type="finder", sub_agent_desc="inspect shared tasks", sub_agent_prompt="prompt"
                    ),
                )
            )
            shell = _snapshot()
            shared_shell = BackgroundTaskSnapshot(
                ref=TaskReference(kind="shell", owner_session_id="main", task_id=shell.task_id, run_id=shell.task_id),
                shell=shell,
                status="running",
                started_at=1,
                delivery_id="shell-result",
            )
            foreground = shared_shell.model_copy(
                update={
                    "ref": shared_shell.ref.model_copy(update={"task_id": "foreground"}),
                    "shell": shell.model_copy(update={"task_id": "foreground", "background": False}),
                }
            )
            snapshot = events.BackgroundTasksUpdatedEvent(
                session_id="main", tasks=[task_snapshot(), shared_shell, foreground]
            )
            await emit(snapshot)
            await emit(
                events.ToolResultEvent(
                    session_id="main",
                    tool_call_id="launch",
                    tool_name=tools.AGENT,
                    status="success",
                    result='{"status":"running"}',
                    ui_extra=SessionIdUIExtra(session_id="child"),
                )
            )
            await emit(events.ShellTasksUpdatedEvent(session_id="main", tasks=[shell]))
            if finish == "finish":
                await emit(events.TaskFinishEvent(session_id="main", task_result="done"))
            else:
                await emit(events.InterruptEvent(session_id="main"))
            for control in (None, events.ToggleTranscriptDetailEvent, events.RefreshDisplayEvent):
                if control is not None:
                    await emit(control(session_id="main"))
                assert display._machine._sessions["child"].task_active
                rows = updates[-1]
                assert any("inspect shared tasks" in line.text for line in rows)
                footer = rows[-1].text
                state = "Paused" if finish == "interrupt" else "Awaiting"
                assert footer.startswith(f" ◈  {state} · 1 agent · 1 shell")
                assert "/stop agents" in footer and "Esc main" not in footer
                assert (
                    len(
                        [
                            line
                            for line in display._tape.snapshot()
                            if isinstance(line, events.BackgroundTasksUpdatedEvent)
                        ]
                    )
                    == 1
                )
            await emit(events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[]))
            assert not display._machine._sessions["child"].task_active
            assert not any("Background tasks" in line.text for line in updates[-1])
        finally:
            await display.stop()

    asyncio.run(run())


def test_queued_snapshot_without_child_identity_has_visible_row() -> None:
    machine = DisplayStateMachine()
    machine.transition(_welcome("main"))
    queued = task_snapshot(
        "queued", ref=TaskReference(kind="agent", owner_session_id="main", task_id="queued", run_id="queued")
    )
    machine.transition(events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[queued]))
    assert machine._sessions["task:queued"].task_active
    machine.transition(events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[task_snapshot()]))
    assert not machine._sessions["task:queued"].task_active
    assert machine._sessions["child"].task_active


def test_background_metadata_is_independent_and_terminal_snapshot_does_not_generate_assistant() -> None:
    # Compact mode folds background cost into the batch block; full mode prints it once.
    machine = DisplayStateMachine(detail=TranscriptDetail(Detail.FULL))
    machine.transition(_welcome("main"))
    machine.transition(events.TaskStartEvent(session_id="main"))
    metadata = TaskMetadata(model_name="child-model", usage=Usage(input_tokens=20, output_tokens=10, input_cost=0.01))
    done = task_snapshot("completed", result=BackgroundTaskResult(text="", metadata=metadata), ended_at=2)
    snapshot = events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[done])
    commands = machine.transition(snapshot)
    assert len([cmd for cmd in commands if isinstance(cmd, RenderTaskMetadata)]) == 1
    assert not any(isinstance(cmd, (AppendAssistant, SpinnerStop)) for cmd in commands)
    assert machine._sessions["main"].task_active
    assert not any(isinstance(cmd, RenderTaskMetadata) for cmd in machine.transition(snapshot))
    historical = events.TaskMetadataEvent(
        session_id="main",
        metadata=TaskMetadataItem(
            background_task_id="agent-1",
            sub_agent_task_metadata=[metadata],
        ),
    )
    assert machine.transition(historical) == []


def test_old_run_snapshots_preserve_new_child_turn_and_account_for_each_run() -> None:
    # Compact mode folds background cost into the batch block; full mode prints it once.
    machine = DisplayStateMachine(detail=TranscriptDetail(Detail.FULL))
    machine.transition(_welcome("main"))
    done = task_snapshot(
        "completed",
        ended_at=2,
        result=BackgroundTaskResult(
            text="", metadata=TaskMetadata(model_name="child-model", usage=Usage(input_tokens=10))
        ),
    )
    second = done.model_copy(
        update={"ref": done.ref.model_copy(update={"task_id": "agent-2"}), "started_at": 3, "ended_at": 4}
    )
    commands = machine.transition(events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[done, second]))
    assert {
        command.event.metadata.background_task_id for command in commands if isinstance(command, RenderTaskMetadata)
    } == {"agent-1", "agent-2"}
    machine.transition(
        events.TaskStartEvent(
            session_id="child",
            parent_session_id="main",
            timestamp=5,
            sub_agent_state=SubAgentState(sub_agent_type="finder", sub_agent_desc="new run", sub_agent_prompt="prompt"),
        )
    )
    machine.transition(events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[done, second]))
    assert machine._sessions["child"].task_active


@pytest.mark.parametrize("failed", [False, True])
def test_parallel_child_results_survive_interleaved_completed_snapshots(failed: bool) -> None:
    machine = DisplayStateMachine()
    machine.transition(_welcome("main"))
    snapshots: list[BackgroundTaskSnapshot] = []
    for index, child_id in enumerate(("child-a", "child-b")):
        machine.transition(
            events.TaskStartEvent(
                session_id=child_id,
                parent_session_id="main",
                timestamp=1,
                sub_agent_state=SubAgentState(
                    sub_agent_type="finder",
                    sub_agent_desc=f"task {index}",
                    sub_agent_prompt="prompt",
                    parent_tool_batch_id="parallel-batch",
                    parent_tool_batch_index=index,
                    parent_tool_batch_size=2,
                ),
            )
        )
        snapshots.append(
            task_snapshot(
                ref=TaskReference(
                    kind="agent", owner_session_id="main", task_id=child_id, run_id=child_id, session_id=child_id
                )
            )
        )
    machine.transition(events.BackgroundTasksUpdatedEvent(session_id="main", tasks=snapshots))
    first_result = "Cannot read repository" if failed else "Found the replay path"
    first_finish = (
        events.ErrorEvent(session_id="child-a", error_message=first_result, can_retry=False, timestamp=2)
        if failed
        else events.TaskFinishEvent(session_id="child-a", task_result=first_result, timestamp=2)
    )
    assert not any(isinstance(cmd, RenderSubAgentBatchSummary) for cmd in machine.transition(first_finish))
    snapshots[0] = snapshots[0].model_copy(
        update={"status": "completed", "ended_at": 2, "result": BackgroundTaskResult(text="snapshot fallback")}
    )
    for _ in range(2):
        commands = machine.transition(events.BackgroundTasksUpdatedEvent(session_id="main", tasks=snapshots))
        assert not any(isinstance(cmd, RenderSubAgentBatchSummary) for cmd in commands)
        assert machine._sessions["child-a"].result_summary == first_result
        assert machine._sessions["child-a"].terminal_status == ("error" if failed else "success")
    commands = machine.transition(
        events.TaskFinishEvent(session_id="child-b", task_result="Second result", timestamp=3)
    )
    batch = next(cmd for cmd in commands if isinstance(cmd, RenderSubAgentBatchSummary))
    assert [summary.result_summary for summary in batch.summaries] == [first_result, "Second result"]
    assert [summary.status for summary in batch.summaries] == ["error" if failed else "success", "success"]
    snapshots[1] = snapshots[1].model_copy(update={"status": "completed", "ended_at": 3})
    assert not any(
        isinstance(cmd, RenderSubAgentBatchSummary)
        for cmd in machine.transition(events.BackgroundTasksUpdatedEvent(session_id="main", tasks=snapshots))
    )


@pytest.mark.parametrize("placeholder", [None, "", "Task cancelled", "Task canceled"])
@pytest.mark.parametrize("snapshot_text", ["", "Snapshot result"])
def test_terminal_snapshot_fills_missing_or_cancelled_child_result(placeholder: str | None, snapshot_text: str) -> None:
    machine = DisplayStateMachine()
    machine.transition(_welcome("main"))
    machine.transition(events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[task_snapshot()]))
    if placeholder is not None:
        machine.transition(events.TaskFinishEvent(session_id="child", task_result=placeholder, timestamp=2))
    snapshot = task_snapshot("failed", ended_at=2, result=BackgroundTaskResult(text=snapshot_text, error=True))
    machine.transition(events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[snapshot]))
    child = machine._sessions["child"]
    assert child.result_summary == (snapshot_text or "failed")
    assert child.terminal_status == "error"


@pytest.mark.parametrize("status", ["completed", "failed", "rejected"])
def test_stop_receipt_reports_actual_operation_outcome(status: str) -> None:
    machine = DisplayStateMachine()
    event = events.OperationFinishedEvent.model_validate(
        {
            "session_id": "main",
            "operation_id": "stop",
            "operation_type": "stop_sub_agents",
            "status": status,
            "error_message": "cannot stop" if status != "completed" else None,
        }
    )
    notice = next(cmd for cmd in machine.transition(event) if isinstance(cmd, RenderNotice)).event
    assert notice.is_error == (status != "completed")
    assert ("Child agents stopped" in notice.content) == (status == "completed")


def test_stop_is_registered_for_immediate_completion() -> None:
    assert has_background_command("/stop")
    assert "child agents" in next(info.summary for info in get_command_info_list() if info.name == "stop")


def test_child_peer_message_is_not_hidden_with_ordinary_child_prompts() -> None:
    machine = DisplayStateMachine()
    machine.transition(
        events.TaskStartEvent(
            session_id="child",
            parent_session_id="main",
            sub_agent_state=SubAgentState(sub_agent_type="finder", sub_agent_desc="inspect", sub_agent_prompt="prompt"),
        )
    )
    assert machine.transition(events.UserMessageEvent(session_id="child", content="ordinary prompt")) == []
    peer = PeerMessage(sender_label="Alice", recipient="child", body="coordination")
    commands = machine.transition(
        events.UserMessageEvent(session_id="child", source="peer_message", peer_message=peer, content=peer.input_text())
    )
    assert any(isinstance(command, RenderUserMessage) for command in commands)


def test_peer_and_task_reports_survive_history_and_tape_detail_toggle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def run() -> None:
        writes = patch_scrollback_writes(monkeypatch)
        peer = PeerMessage(
            id="peer-id",
            sender_session_id="sender",
            sender_label="Alice",
            recipient="main",
            body="first line\nfull body",
            reply_to="earlier-id",
        )
        session = Session(
            id="main",
            work_dir=tmp_path,
            conversation_history=[
                message.UserMessage(
                    source="peer_message", peer_message=peer, parts=[message.TextPart(text=peer.input_text())]
                ),
                message.AssistantMessage(parts=[message.TextPart(text="root answer")], stop_reason="stop"),
                TaskMetadataItem(),
                TaskMetadataItem(
                    background_task_id="agent-1",
                    sub_agent_task_metadata=[TaskMetadata(model_name="child-model", usage=Usage(input_tokens=10))],
                ),
                message.UserMessage(
                    source="task_completion",
                    parts=[
                        message.TextPart(
                            text="source=background_task\n"
                            + TaskResponse(
                                tasks=[task_snapshot("completed")], output="task report body"
                            ).model_dump_json()
                        )
                    ],
                ),
            ],
        )
        history = list(session.get_history_item())
        assert len([event for event in history if isinstance(event, events.TaskStartEvent)]) == 1
        assert len([event for event in history if isinstance(event, events.TaskFinishEvent)]) == 1
        display = TUIDisplay()
        try:
            await display.consume_envelope(make_envelope(_welcome("main")))
            await display.consume_envelope(
                make_envelope(events.ReplayHistoryEvent(session_id="main", events=history, updated_at=0))
            )
            compact = writes[-1][0]
            # Compact mode previews the first paragraph as one wrapped row, without metadata.
            assert "› Message from Alice: first line full body" in compact
            assert "reply_to:" not in compact
            # With no live snapshot, the report itself builds the agent's batch block, once.
            assert compact.count("Agent: inspect shared tasks ✓") == 1 and "task report body" in compact
            assert "Background task" not in compact and "agent-1" not in compact
            await display.consume_envelope(make_envelope(events.ToggleTranscriptDetailEvent(session_id="main")))
            expanded = writes[-1][0]
            for value in ("full body", "sender: sender", "recipient: main", "id: peer-id", "reply_to: earlier-id"):
                assert value in expanded
            await display.consume_envelope(make_envelope(events.RefreshDisplayEvent(session_id="main")))
            assert "full body" in writes[-1][0]
        finally:
            await display.stop()

    asyncio.run(run())


def test_control_result_and_native_tools_are_readable_and_pageable() -> None:
    response = TaskResponse(
        tasks=[task_snapshot("completed")],
        output="\n".join(f"line {i}" for i in range(20)),
        truncated=True,
        next_offset=42,
    )
    compact = plain(render_task_response(response, detail=Detail.COMPACT))
    assert "line 19" not in compact and "/tasks output agent-1 42" in compact
    expanded = plain(render_task_response(response, detail=Detail.FULL))
    assert "line 19" in expanded
    managed = render_collaboration_result(
        tools.MANAGE_TASKS, "source=background_task\n" + response.model_dump_json(), detail=Detail.COMPACT
    )
    assert managed is not None and "agent-1" in plain(managed)
    peers = render_collaboration_result(
        tools.LIST_PEERS,
        '{"peers":[{"session_id":"peer-id","name":"Alice","state":"running","work_dir":"/tmp"}]}',
        detail=Detail.COMPACT,
    )
    assert peers is not None and "Alice" in plain(peers) and '"session_id"' not in plain(peers)
    receipt = render_collaboration_result(
        tools.MESSAGE_PEER, '{"message_id":"message-id","target":"peer","accepted":true}', detail=Detail.COMPACT
    )
    assert receipt is not None and "not read" in plain(receipt)
    outgoing = get_tool_call_presentation(tools.MESSAGE_PEER, '{"target":"Alice","body":"summary\\nprivate detail"}')
    assert "Alice" in outgoing.subject and "summary" in outgoing.subject and "private detail" not in outgoing.subject


def test_long_task_report_only_points_to_result_and_plain_user_is_not_a_peer() -> None:
    response = TaskResponse(tasks=[task_snapshot("completed")], output="long body" * 2000)
    event = events.UserMessageEvent(
        session_id="main", source="task_completion", content="source=background_task\n" + response.model_dump_json()
    )
    # Compact mode reports a finished agent through its batch block, not this message.
    assert render_sourced_message(event, detail=Detail.COMPACT) is None
    rendered = plain(render_sourced_message(event, detail=Detail.FULL))
    assert "/tasks output agent-1" in rendered and "long body" not in rendered
    renderer = TUICommandRenderer()
    with renderer.bulk_render_capture() as capture:
        renderer.display_user_message(
            events.UserMessageEvent(session_id="main", content="<agent-message>plain input</agent-message>")
        )
    assert "plain input" in capture.getvalue() and "来自" not in capture.getvalue()


@pytest.mark.parametrize("max_lines", [6, 50])
def test_manage_tasks_expanded_tool_output_respects_line_budget_and_pagination(max_lines: int) -> None:
    response = TaskResponse(
        tasks=[task_snapshot("completed")],
        output="\n".join(f"output line {index}" for index in range(1000)),
        truncated=True,
        next_offset=8192,
    )
    result = render_tool_result(
        events.ToolResultEvent(
            session_id="main",
            tool_call_id="output",
            tool_name=tools.MANAGE_TASKS,
            status="success",
            result=response.model_dump_json(),
        ),
        detail=Detail.FULL,
        max_lines=max_lines,
    )
    assert result is not None
    rendered = plain(result)
    assert "output line 0" in rendered and "output line 999" in rendered
    assert "output line 500" not in rendered
    assert f"more {1000 - max_lines} lines" in rendered
    assert rendered.count("output line ") == max_lines
    assert "/tasks output agent-1 8192" in rendered
    operator_page = plain(render_task_response(response, detail=Detail.FULL))
    assert "output line 500" in operator_page


def test_socket_shared_snapshot_preserves_idle_and_peer_is_not_swallowed() -> None:
    async def run() -> None:
        async def ignore(_envelope: events.EventEnvelope) -> None:
            pass

        client = SocketRuntimeClient("main", on_envelope=ignore)
        client._pending_echo_swallows.append(("same text", time.monotonic()))
        peer = PeerMessage(sender_label="Alice", recipient="main", body="same text")
        event = events.UserMessageEvent(
            session_id="main", content="same text", source="peer_message", peer_message=peer
        )
        await client._handle_envelope(_local_envelope(event))
        client.state_changed_event().clear()
        snapshot = events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[task_snapshot()])
        await client._handle_frame(make_envelope(snapshot).model_dump(mode="json", serialize_as_any=True))
        assert not client.is_running() and not client.state_changed_event().is_set()
        assert "child" in client._child_session_ids
        assert client._display_queue.get_nowait().event == event
        assert isinstance(client._display_queue.get_nowait().event, events.BackgroundTasksUpdatedEvent)
        await client._handle_frame(
            make_envelope(events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[])).model_dump(
                mode="json", serialize_as_any=True
            )
        )
        assert not client.is_running() and not client.state_changed_event().is_set()
        interaction = events.UserInteractionRequestEvent(
            session_id="child",
            request_id="question",
            source="tool",
            payload=AskUserQuestionRequestPayload(questions=[]),
        )
        await client._handle_envelope(_local_envelope(interaction))
        assert client._interaction_queue.get_nowait() == interaction

    asyncio.run(run())


@pytest.mark.parametrize(("columns", "height"), [(80, 24), (60, 20)])
def test_attention_priority_bounded_rows_and_finished_access_survive_replay(
    monkeypatch: pytest.MonkeyPatch, columns: int, height: int
) -> None:
    async def run() -> None:
        patch_scrollback_writes(monkeypatch)
        monkeypatch.setattr(machine_module, "_terminal_columns_cache", (time.monotonic(), columns))
        monkeypatch.setattr(machine_module, "_terminal_lines_cache", (time.monotonic(), height))
        updates: list[tuple[PromptStatusLine, ...]] = []
        display = TUIDisplay(on_status_update=lambda lines, *_: updates.append(lines))
        display._renderer.console.width = columns
        display.set_progress_ui_suspended(True)

        async def emit(event: events.Event) -> None:
            await display.consume_envelope(make_envelope(event))
            display.refresh_prompt_status()

        try:
            await emit(_welcome("main"))
            await emit(events.TaskStartEvent(session_id="main"))
            snapshots = [
                task_snapshot(
                    ref=TaskReference(
                        kind="agent",
                        owner_session_id="main",
                        task_id=f"task-{index}",
                        run_id=f"run-{index}",
                        session_id=f"child-{index}",
                    ),
                    description=f"Investigate component {index}",
                    started_at=time.time(),
                )
                for index in range(8)
            ]
            snapshots.append(task_snapshot("failed", description="Completed failure", delivered=True))
            snapshot = events.BackgroundTasksUpdatedEvent(session_id="main", tasks=snapshots)
            await emit(snapshot)
            request = events.UserInteractionRequestEvent(
                session_id="child-7",
                request_id="approval",
                source="approval",
                payload=AskUserQuestionRequestPayload(questions=[]),
            )
            for _ in range(2):
                await emit(request)
                await emit(snapshot)
            await emit(events.InterruptEvent(session_id="main"))
            before = tuple(line.text for line in updates[-1])
            assert "Investigate component 7" in before[0] and "Waiting for approval" in before[0]
            assert sum("Investigate component" in line for line in before) == 8
            assert not any("unread" in line.lower() or "Completed failure" in line for line in before)
            assert before[-1].startswith(" ◈  Paused · 8 agents · 1 needs attention · 1 failed  /tasks")
            assert "Esc main" not in before[-1]
            for control in (
                events.RefreshDisplayEvent,
                events.ToggleTranscriptDetailEvent,
                events.ToggleTranscriptDetailEvent,
            ):
                await emit(control(session_id="main"))
                assert display.task_attention() == {"child-7": "Waiting for approval"}
                assert "Investigate component 7" in updates[-1][0].text
            assert tuple(line.text for line in updates[-1]) == before
            await emit(
                events.UserInteractionCancelledEvent(
                    session_id="child-7", request_id="approval", reason="user_cancelled"
                )
            )
            assert display.task_attention() == {}
            assert not any("Waiting for approval" in line.text for line in updates[-1])
            await emit(
                events.UserInteractionResolvedEvent(session_id="child-7", request_id="approval", status="cancelled")
            )
            assert display.task_attention() == {}
        finally:
            await display.stop()

    asyncio.run(run())
