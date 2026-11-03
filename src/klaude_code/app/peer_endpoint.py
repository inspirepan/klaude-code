"""Per-process Unix socket discovery and authenticated peer delivery."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from klaude_code.app.interaction_reply import HeadlessRespondRequest, _build_interaction_response
from klaude_code.app.process_queries import session_snapshot
from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.app.scheduler import HeadlessRuntime
from klaude_code.app.session_state import live_descendant_session_ids
from klaude_code.app.session_view import serialize_pending_request
from klaude_code.protocol import events, op
from klaude_code.protocol.background_task import TaskRequest
from klaude_code.protocol.peer import PeerInfo, PeerMessage, PeerReceipt

_FRAME_LIMIT = 64 * 1024 * 1024


class EndpointRecord(BaseModel):
    id: str
    pid: int
    socket_path: str
    token: str
    sessions: list[PeerInfo]


def endpoint_directory() -> Path:
    return Path.home() / ".klaude" / "run" / "peers"


def registered_endpoints() -> list[EndpointRecord]:
    records: list[EndpointRecord] = []
    for path in endpoint_directory().glob("*.json"):
        try:
            record = EndpointRecord.model_validate_json(path.read_text())
            os.kill(record.pid, 0)
        except (OSError, ValueError):
            continue
        records.append(record)
    return records


async def call_endpoint(record: EndpointRecord, method: str, **payload: Any) -> Any:
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(record.socket_path, limit=_FRAME_LIMIT),
        timeout=5,
    )
    try:
        request = {"method": method, "token": record.token, **payload}
        writer.write(json.dumps(request).encode() + b"\n")
        await writer.drain()
        wait_ms = int(payload.get("request", {}).get("wait_ms", 0)) if method == "tasks" else 0
        raw = await asyncio.wait_for(reader.readline(), timeout=max(35, wait_ms / 1000 + 15))
        response = json.loads(raw)
        if "error" in response:
            raise ValueError(response["error"])
        return response["result"]
    finally:
        writer.close()
        await writer.wait_closed()


class PeerEndpoint:
    def __init__(self, runtime: RuntimeFacade, scheduler: HeadlessRuntime) -> None:
        self.runtime = runtime
        self.scheduler = scheduler
        endpoint_id = uuid4().hex
        home_hash = hashlib.sha256(str(Path.home()).encode()).hexdigest()[:12]
        socket_root = Path("/tmp") / f"klaude-{os.getuid()}-{home_hash}"
        socket_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.record = EndpointRecord(
            id=endpoint_id,
            pid=os.getpid(),
            socket_path=str(socket_root / f"{endpoint_id[:16]}.sock"),
            token=secrets.token_hex(32),
            sessions=[],
        )
        self._server: asyncio.Server | None = None
        self._handlers: set[asyncio.Task[Any]] = set()
        self._published = ""
        self.accepting_input = True
        self._turn_text: dict[str, str] = {}

    def observe(self, event: events.Event) -> None:
        if isinstance(event, events.TaskStartEvent):
            self._turn_text[event.session_id] = ""
        elif isinstance(event, events.AssistantTextDeltaEvent):
            self._turn_text[event.session_id] = self._turn_text.get(event.session_id, "") + event.content

    async def start(self) -> None:
        self._server = await asyncio.start_unix_server(self._receive, self.record.socket_path, limit=_FRAME_LIMIT)
        os.chmod(self.record.socket_path, 0o600)
        self.runtime.peer_control.list_callback = self.list_peers
        self.runtime.peer_control.send_callback = self.send_peer
        self.refresh()

    def refresh(self) -> None:
        self.record.sessions = [
            PeerInfo(
                session_id=agent.session.id,
                name=agent.session.name,
                state=self.scheduler.session_status(agent.session.id).category,
                description=agent.session.title or "",
                work_dir=str(agent.session.work_dir),
            )
            for actor in self.runtime.session_registry.list_session_actors()
            if (agent := actor.get_agent()) is not None
        ]
        content = self.record.model_dump_json()
        if content == self._published:
            return
        root = endpoint_directory()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = root / f"{self.record.id}.json"
        temporary = path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as file:
            file.write(content)
        temporary.replace(path)
        self._published = content

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        for task in list(self._handlers):
            task.cancel()
        await asyncio.gather(*self._handlers, return_exceptions=True)
        for path in (endpoint_directory() / f"{self.record.id}.json", Path(self.record.socket_path)):
            path.unlink(missing_ok=True)

    async def _receive(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(task)
        try:
            try:
                request = json.loads(await asyncio.wait_for(reader.readline(), timeout=10))
                if not secrets.compare_digest(str(request.get("token", "")), self.record.token):
                    raise ValueError("Invalid endpoint credentials")
                result = await self._dispatch(request)
                response = {"result": result}
            except Exception as exc:
                response = {"error": str(exc)}
            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()
            if task is not None:
                self._handlers.discard(task)

    async def _dispatch(self, request: dict[str, Any]) -> Any:
        if request["method"] == "info":
            self.refresh()
            return self.record.model_dump(mode="json")
        if not self.accepting_input and request["method"] != "snapshot":
            raise ValueError("Session process is shutting down; input was not accepted")
        if request["method"] != "deliver":
            return await self._control(request)
        peer = PeerMessage.model_validate(request["message"])
        own = {item.session_id: item for item in self.record.sessions}
        if peer.recipient not in own:
            raise ValueError("Recipient is offline")
        origin = request.get("origin")
        if origin is None:
            peer.sender_session_id = None
        else:
            origin_record = next((item for item in registered_endpoints() if item.id == origin.get("endpoint")), None)
            if origin_record is None or not secrets.compare_digest(str(origin.get("token", "")), origin_record.token):
                raise ValueError("Unverified sender endpoint")
            verified = EndpointRecord.model_validate(await call_endpoint(origin_record, "info"))
            sender = next((item for item in verified.sessions if item.session_id == peer.sender_session_id), None)
            if sender is None or Path(sender.work_dir).resolve() != Path(own[peer.recipient].work_dir).resolve():
                raise ValueError("Sender is outside the reachable scope")
            # Only the receiving Runtime can confer parent identity.
            actor = self.runtime.session_registry.get_session_actor(peer.recipient)
            agent = actor.get_agent() if actor is not None else None
            if agent is not None and peer.sender_session_id == agent.session.parent_session_id:
                raise ValueError("Parent identity requires an owned in-process sender")
        receipt = await self.scheduler.deliver_peer(
            peer,
            Path(own[peer.recipient].work_dir),
            expected_operation_id=request.get("expected_operation_id"),
        )
        return receipt.model_dump(mode="json")

    def _pending_requests(self, session_id: str):
        ids = {session_id, *live_descendant_session_ids(self.runtime.session_registry, session_id)}
        return [
            pending
            for actor in self.runtime.session_registry.list_session_actors()
            if actor.session_id in ids
            for pending in actor.pending_requests_snapshot()
        ]

    async def _control(self, request: dict[str, Any]) -> Any:
        session_id = str(request.get("session_id", ""))
        actor = self.runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        if agent is None:
            raise ValueError("Session is offline")
        work_dir = agent.session.work_dir
        method = request["method"]
        if method == "tasks":
            result = await self.runtime.task_manager.manage(
                session_id, work_dir, TaskRequest.model_validate(request["request"])
            )
            return result.model_dump(mode="json")
        if method == "control":
            action = request.get("action")
            if action not in {"resume", "dismiss"}:
                raise ValueError("Invalid control action")
            await self.scheduler.control_session(session_id, work_dir, action=action)
        elif method in {"interrupt", "stop", "stop-children"}:
            if method != "stop-children":
                await self.scheduler.prepare_interrupt(session_id, work_dir)
            operation = (
                op.StopAllTasksOperation(session_id=session_id)
                if method == "stop"
                else op.StopSubAgentsOperation(session_id=session_id)
                if method == "stop-children"
                else op.InterruptOperation(session_id=session_id)
            )
            await self._execute_control(operation)
        elif method == "respond":
            pending = self._pending_requests(session_id)
            if not pending:
                raise ValueError("Session has no pending interaction request")
            response = _build_interaction_response(
                pending[0], HeadlessRespondRequest.model_validate(request["response"])
            )
            await self._execute_control(
                op.UserInteractionRespondOperation(
                    session_id=pending[0].session_id,
                    request_id=pending[0].request_id,
                    response=response,
                )
            )
        elif method != "snapshot":
            raise ValueError("Unknown endpoint method")
        status = self.scheduler.session_status(session_id)
        result = session_snapshot(
            agent.session,
            status=status,
            pending=self.scheduler.has_pending(session_id),
            turns=request.get("turns"),
            transcript=bool(request.get("transcript")),
            summary_only=bool(request.get("summary")),
        )
        pending = self._pending_requests(session_id)
        if pending:
            result["pending_request"] = serialize_pending_request(pending[0])
        result["ok"] = True
        if not request.get("summary"):
            result["streaming_output"] = self._turn_text.get(session_id, "")
        return result

    async def _execute_control(self, operation: op.Operation) -> None:
        operation_id = await self.runtime.submit(operation)
        status = await self.runtime.wait_for(operation_id)
        if status != "completed":
            raise RuntimeError(f"{operation.type.value} {status or 'did not finish'}")

    async def _online(self) -> list[EndpointRecord]:
        records = [record for record in registered_endpoints() if record.id != self.record.id]
        replies = await asyncio.gather(*(call_endpoint(record, "info") for record in records), return_exceptions=True)
        return [EndpointRecord.model_validate(reply) for reply in replies if isinstance(reply, dict)]

    async def list_peers(self, sender: str, work_dir: Path) -> list[PeerInfo]:
        self.refresh()
        actor = self.runtime.session_registry.get_session_actor(sender)
        agent = actor.get_agent() if actor is not None else None
        if agent is None:
            raise ValueError("Sender is not owned by this process")
        local = [
            item
            for item in self.record.sessions
            if item.session_id != sender
            and (
                Path(item.work_dir).resolve() == work_dir.resolve()
                or item.session_id == agent.session.parent_session_id
                or (
                    (child_actor := self.runtime.session_registry.get_session_actor(item.session_id)) is not None
                    and (child := child_actor.get_agent()) is not None
                    and child.session.parent_session_id == sender
                )
            )
        ]
        remote = [
            item
            for record in await self._online()
            for item in record.sessions
            if Path(item.work_dir).resolve() == work_dir.resolve() and item.session_id != sender
        ]
        return [*local, *remote]

    async def send_peer(self, sender: str, target: str, body: str, reply_to: str | None) -> PeerReceipt:
        origin = next((item for item in self.record.sessions if item.session_id == sender), None)
        if origin is None:
            raise ValueError("Sender is not owned by this process")
        candidates = await self.list_peers(sender, Path(origin.work_dir))
        exact = [item for item in candidates if item.session_id == target or item.name == target]
        matches = exact or [item for item in candidates if item.session_id.startswith(target)]
        if len(matches) != 1:
            raise ValueError("Peer target is unavailable or ambiguous")
        recipient = matches[0]
        peer = PeerMessage(
            sender_session_id=sender,
            sender_label=origin.name or origin.description or sender,
            recipient=recipient.session_id,
            body=body,
            reply_to=reply_to,
        )
        if any(item.session_id == peer.recipient for item in self.record.sessions):
            return await self.scheduler.deliver_peer(peer, Path(recipient.work_dir))
        record = next(
            (
                record
                for record in await self._online()
                if any(item.session_id == peer.recipient for item in record.sessions)
            ),
            None,
        )
        if record is None:
            raise ValueError("Peer went offline")
        return PeerReceipt.model_validate(
            await call_endpoint(
                record,
                "deliver",
                message=peer.model_dump(mode="json"),
                origin={"endpoint": self.record.id, "token": self.record.token},
            )
        )
