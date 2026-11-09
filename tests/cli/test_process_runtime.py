from __future__ import annotations

import asyncio
import json
import multiprocessing
import time
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from klaude_code.cli.process_client import request
from klaude_code.session import Session


def _headless_worker(connection: Connection, directory: str, terminate: bool = False) -> None:
    from klaude_code.agent.runtime.llm import LLMClients
    from klaude_code.cli.process_worker import run_background
    from klaude_code.protocol import message
    from tests.fake_llm import FakeLLMClient

    client = FakeLLMClient()
    client.enqueue(
        message.AssistantMessage(
            parts=[
                message.ToolCallPart(
                    call_id="shell",
                    tool_name="Bash",
                    arguments_json=json.dumps(
                        {
                            "command": "sleep 60" if terminate else "sleep 0.3; printf shell-completed",
                            "run_in_background": True,
                        }
                    ),
                )
            ]
        )
    )
    client.enqueue(
        message.AssistantMessage(parts=[message.TextPart(text="headless result")]), delay_s=60 if terminate else 0.05
    )
    clients = LLMClients(main=client, main_model_alias="fake")
    with (
        patch("klaude_code.app.runtime.build_llm_clients", return_value=clients),
        patch("klaude_code.agent.runtime.agent_ops.build_llm_clients", return_value=clients),
        patch("klaude_code.agent.runtime.llm.clone_llm_client", side_effect=lambda value: value),
        patch("klaude_code.agent.runtime.agent_ops.generate_session_title", new=AsyncMock(return_value=None)),
    ):
        try:
            asyncio.run(
                run_background(
                    {
                        "session_id": "headless-independent",
                        "work_dir": directory,
                        "prompt": "start background work",
                    },
                    connection.send,
                )
            )
        except asyncio.CancelledError:
            if not terminate:
                raise


def test_headless_process_finishes_owned_shell_and_offline_queries_work(tmp_path: Path, isolated_home: Path) -> None:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_headless_worker, args=(child, str(tmp_path)))
    process.start()
    child.close()
    try:
        assert parent.poll(15)
        ready = parent.recv()
        session_id = ready["session_id"]
        assert process.is_alive()
        status, body = request("GET", "/api/headless/sessions", params={"targets": session_id})
        assert status == 200
        assert body["sessions"][0]["id"] == session_id
        assert "output" not in body["sessions"][0]
        assert "streaming_output" not in body["sessions"][0]
        process.join(15)
        assert process.exitcode == 0

        status, body = request("GET", f"/api/headless/sessions/{session_id}/output")
        assert status == 200
        assert body["output"] == "headless result"
        assert body["status"]["last_turn"]["result"] == "succeeded"
        assert request("GET", "/api/headless/sessions")[1]["sessions"] == []
        history = request("GET", "/api/headless/sessions", params={"history": True})[1]["sessions"]
        assert history[0]["id"] == session_id
        assert history[0]["online"] is False

        status, body = request("POST", f"/api/headless/sessions/{session_id}/send", json_body={"text": "offline"})
        assert status == 400 and "offline" in body["detail"]
        session = Session.load(session_id, work_dir=tmp_path)
        assert not session.steering_queue
        tasks = list((isolated_home / ".klaude" / "projects").glob("*/sessions/*/shell_tasks/*.json"))
        assert len(tasks) == 1
        assert json.loads(tasks[0].read_text())["status"] == "completed"
        assert "shell-completed" in "".join(path.read_text() for path in tasks[0].parent.glob("*.log"))
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()


def test_sigterm_stops_owned_shell_and_unregisters_process(tmp_path: Path, isolated_home: Path) -> None:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_headless_worker, args=(child, str(tmp_path), True))
    process.start()
    child.close()
    try:
        assert parent.poll(15)
        session_id = parent.recv()["session_id"]
        body = {"tasks": []}
        for _ in range(100):
            status, body = request("POST", f"/api/headless/sessions/{session_id}/tasks", json_body={"action": "list"})
            if status == 200 and body["tasks"]:
                break
            time.sleep(0.02)
        assert body["tasks"] and body["tasks"][0]["status"] == "running"
        process.terminate()
        process.join(15)
        assert process.exitcode == 0
        tasks = list((isolated_home / ".klaude" / "projects").glob("*/sessions/*/shell_tasks/*.json"))
        assert len(tasks) == 1 and json.loads(tasks[0].read_text())["status"] == "stopped"
        assert request("GET", "/api/headless/sessions")[1]["sessions"] == []
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        parent.close()


def _headless_agent_worker(connection: Connection, directory: str) -> None:
    from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
    from klaude_code.agent.runtime.llm import LLMClients
    from klaude_code.cli.process_worker import run_background
    from klaude_code.config import Config
    from klaude_code.protocol import llm_param, tools
    from tests.app.test_local_agent_e2e import reply, tool
    from tests.fake_llm import FakeLLMClient, ScriptedLLMStream

    client = FakeLLMClient()
    parent_calls = 0

    async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
        nonlocal parent_calls
        if param.session_id != "headless-native-agent":
            await asyncio.to_thread(connection.recv)
            return reply("child report")
        parent_calls += 1
        if parent_calls == 1:
            return tool(tools.AGENT, {"description": "held child", "prompt": "work"}, "launch")
        return reply("report acknowledged" if parent_calls == 3 else "parent finished")

    with (
        patch.object(client, "call", scripted),
        patch(
            "klaude_code.app.runtime.build_llm_clients",
            side_effect=lambda *_a, **_k: LLMClients(main=client, main_model_alias="fake"),
        ),
        patch(
            "klaude_code.agent.runtime.agent_ops.build_llm_clients",
            side_effect=lambda *_a, **_k: LLMClients(main=client, main_model_alias="fake"),
        ),
        patch("klaude_code.agent.runtime.llm.clone_llm_client", side_effect=lambda value: value),
        patch("klaude_code.agent.runtime.sub_agent.load_config", return_value=Config(provider_list=[])),
        patch.object(AgentOperationHandler, "_schedule_session_title_refresh"),
        patch.object(AgentOperationHandler, "_schedule_prompt_suggestion"),
    ):
        asyncio.run(
            run_background(
                {
                    "session_id": "headless-native-agent",
                    "work_dir": directory,
                    "prompt": "delegate",
                },
                connection.send,
            )
        )


def test_headless_process_waits_for_native_agent_report_and_rejects_second_executor(tmp_path: Path) -> None:
    from klaude_code.agent.runtime.llm import LLMClients
    from klaude_code.protocol import events, message
    from klaude_code.tui.client.local import LocalRuntimeClient
    from tests.fake_llm import FakeLLMClient

    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_headless_agent_worker, args=(child, str(tmp_path)))
    process.start()
    child.close()
    try:
        assert parent.poll(15)
        session_id = parent.recv()["session_id"]
        body: dict[str, Any] = {"output": ""}
        for _ in range(200):
            status, body = request("GET", f"/api/headless/sessions/{session_id}/output")
            if status == 200 and body["output"] == "parent finished":
                break
            time.sleep(0.02)
        assert body["output"] == "parent finished" and process.is_alive()
        assert body["status"]["execution"] == "waiting_agents"
        tasks = request("POST", f"/api/headless/sessions/{session_id}/tasks", json_body={"action": "list"})[1]["tasks"]
        assert len(tasks) == 1 and tasks[0]["status"] == "running"

        async def attempt_restore() -> None:
            async def consume(_envelope: events.EventEnvelope) -> None:
                pass

            client = LocalRuntimeClient(session_id, on_envelope=consume, work_dir=tmp_path)
            with patch(
                "klaude_code.app.runtime.build_llm_clients",
                return_value=LLMClients(main=FakeLLMClient(), main_model_alias="fake"),
            ):
                import pytest

                with pytest.raises(ValueError, match="active in another"):
                    await client.start()
            await client.close()

        asyncio.run(attempt_restore())
        parent.send("finish child")
        process.join(15)
        assert process.exitcode == 0
        body = request("GET", f"/api/headless/sessions/{session_id}/output")[1]
        assert body["output"] == "report acknowledged"
        session = Session.load(session_id, work_dir=tmp_path)
        reports = [
            item
            for item in session.conversation_history
            if isinstance(item, message.UserMessage) and item.source == "task_completion"
        ]
        assert len(reports) == 1 and "child report" in message.join_text_parts(reports[0].parts)
        assert request("GET", "/api/headless/sessions")[1]["sessions"] == []
    finally:
        if process.is_alive():
            parent.send("finish child")
            process.terminate()
            process.join(5)
        parent.close()
