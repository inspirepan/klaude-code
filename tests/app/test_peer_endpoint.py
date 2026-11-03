from __future__ import annotations

import asyncio
import multiprocessing
from multiprocessing.connection import Connection
from pathlib import Path
from unittest.mock import patch

import pytest

from klaude_code.app.peer_endpoint import EndpointRecord, call_endpoint, registered_endpoints
from klaude_code.app.session_lease import SessionLease
from klaude_code.protocol.peer import PeerMessage


def _worker(connection: Connection, work_dir: str, home: str, identity: str) -> None:
    import os
    import sys

    os.environ["HOME"] = home
    os.environ["KLAUDE_PROCESS_ENV"] = identity
    os.environ[f"KLAUDE_PROCESS_{identity.upper()}_KEY"] = "dummy-test-key"

    from klaude_code.agent.runtime.llm import LLMClients
    from klaude_code.config import Config
    from klaude_code.config.config import ModelConfig, ProviderConfig
    from klaude_code.protocol import events, llm_param
    from klaude_code.protocol.models.session_status import SessionControl
    from klaude_code.tui.client.local import LocalRuntimeClient
    from tests.fake_llm import FakeLLMClient

    async def run() -> None:
        async def consume(_event: events.EventEnvelope) -> None:
            pass

        clients = LLMClients(main=FakeLLMClient(), main_model_alias="fake")
        config = Config(
            provider_list=[
                ProviderConfig(
                    provider_name=f"env-{name}",
                    protocol=llm_param.LLMClientProtocol.OPENAI,
                    api_key=f"${{KLAUDE_PROCESS_{name.upper()}_KEY}}",
                    model_list=[ModelConfig(model_name=name, model_id=name)],
                )
                for name in ("alpha", "beta")
            ]
        )
        with (
            patch("klaude_code.app.runtime.build_llm_clients", return_value=clients),
            patch("klaude_code.agent.runtime.agent_ops.build_llm_clients", return_value=clients),
            patch("klaude_code.agent.runtime.llm.clone_llm_client", side_effect=lambda value: value),
            patch("klaude_code.tui.client.local.load_config", return_value=config),
        ):
            client = LocalRuntimeClient(None, on_envelope=consume, work_dir=Path(work_dir), vanilla=True)
            await client.start()
            client.start_display()
            agent = client.command_agent()
            agent.session.runtime.control = SessionControl(paused=True, reason="test_pause")
            agent.session.persist_runtime()
            endpoint = client._endpoint
            assert endpoint is not None
            endpoint.refresh()
            connection.send(endpoint.record.model_dump())
            try:
                while True:
                    command = await asyncio.to_thread(connection.recv)
                    if command[0] == "stop":
                        break
                    if command[0] == "list":
                        peers = await endpoint.list_peers(client.session_id, Path(work_dir))
                        connection.send([peer.model_dump() for peer in peers])
                    elif command[0] == "send":
                        receipt = await endpoint.send_peer(client.session_id, command[1], command[2], None)
                        connection.send(receipt.model_dump())
                    elif command[0] == "queue":
                        connection.send([item.model_dump() for item in agent.follow_up_snapshot()])
                    elif command[0] == "environment":
                        catalog = await client.get_model_catalog()
                        shell = await asyncio.create_subprocess_exec(
                            sys.executable,
                            "-c",
                            "import os; print(os.environ['KLAUDE_PROCESS_ENV'])",
                            stdout=asyncio.subprocess.PIPE,
                        )
                        output, _ = await shell.communicate()
                        connection.send(([item.model_name for item in catalog.models], output.decode().strip()))
            finally:
                await client.close()

    asyncio.run(run())


def test_real_process_discovery_delivery_deduplication_and_shutdown(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    context = multiprocessing.get_context("spawn")
    channels = []
    processes = []
    records = []
    try:
        for identity in ("alpha", "beta"):
            parent, child = context.Pipe()
            process = context.Process(target=_worker, args=(child, str(work), str(home), identity))
            process.start()
            child.close()
            channels.append(parent)
            processes.append(process)
            assert parent.poll(15), "Worker failed to publish its endpoint"
            records.append(EndpointRecord.model_validate(parent.recv()))

        first, second = records
        for channel, identity in zip(channels, ("alpha", "beta"), strict=True):
            channel.send(("environment",))
            assert channel.poll(10)
            assert channel.recv() == ([identity], identity)
        sender = first.sessions[0].session_id
        receiver = second.sessions[0].session_id
        channels[0].send(("list",))
        assert channels[0].poll(10)
        assert [peer["session_id"] for peer in channels[0].recv()] == [receiver]
        channels[0].send(("send", receiver, "hello from another process"))
        assert channels[0].poll(10)
        receipt = channels[0].recv()
        assert receipt["mode"] == "queued"
        channels[1].send(("queue",))
        assert channels[1].poll(10)
        queued = channels[1].recv()
        assert len(queued) == 1
        peer = PeerMessage.model_validate(queued[0]["peer_message"])
        assert peer.sender_session_id == sender

        async def retry() -> None:
            payload = peer.model_dump(mode="json")
            result = await call_endpoint(
                second, "deliver", message=payload, origin={"endpoint": first.id, "token": first.token}
            )
            assert result["message_id"] == receipt["message_id"]
            spoofed = PeerMessage(
                recipient=receiver, sender_session_id=sender, sender_label="fake parent", body="external"
            )
            await call_endpoint(second, "deliver", message=spoofed.model_dump(mode="json"))

        asyncio.run(retry())
        channels[1].send(("queue",))
        assert channels[1].poll(10)
        queued = channels[1].recv()
        assert len(queued) == 2
        assert queued[1]["peer_message"]["sender_session_id"] is None
        channels[0].send(("stop",))
        processes[0].join(10)
        assert processes[0].exitcode == 0
        assert not Path(first.socket_path).exists()
        assert processes[1].is_alive()
    finally:
        for channel, process in zip(channels, processes, strict=True):
            if process.is_alive():
                channel.send(("stop",))
                process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
            channel.close()


def test_discovery_ignores_dead_process_registration(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("klaude_code.app.peer_endpoint.endpoint_directory", lambda: tmp_path)
    record = EndpointRecord(id="stale", pid=99999999, socket_path="/tmp/missing", token="stale", sessions=[])
    (tmp_path / "stale.json").write_text(record.model_dump_json())
    assert registered_endpoints() == []


def test_crash_releases_execution_lock_and_stale_endpoint_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_worker, args=(child, str(tmp_path), str(home), "alpha"))
    process.start()
    child.close()
    try:
        assert parent.poll(15)
        record = EndpointRecord.model_validate(parent.recv())
        session_id = record.sessions[0].session_id
        monkeypatch.setattr(Path, "home", lambda: home)
        with pytest.raises(ValueError, match="active in another"):
            SessionLease(session_id)
        process.kill()
        process.join(10)
        assert process.exitcode is not None and process.exitcode != 0
        assert (home / ".klaude" / "run" / "peers" / f"{record.id}.json").exists()
        assert registered_endpoints() == []
        with pytest.raises(OSError):
            asyncio.run(call_endpoint(record, "info"))
        lease = SessionLease(session_id)
        lease.close()
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        parent.close()
