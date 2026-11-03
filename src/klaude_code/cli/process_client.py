"""CLI routing to online process sockets or persisted session history."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from klaude_code.app.peer_endpoint import EndpointRecord, call_endpoint, registered_endpoints
from klaude_code.app.process_queries import offline_status, session_snapshot
from klaude_code.app.session_index import SessionIndex, SessionSummary, SessionTargetError
from klaude_code.app.session_index import resolve_session_target as _resolve
from klaude_code.protocol.peer import PeerMessage
from klaude_code.session import Session


def _summaries() -> list[SessionSummary]:
    index = SessionIndex(home=Path.home())
    index.reload()
    return index.list_all()


async def _online() -> dict[str, EndpointRecord]:
    records = registered_endpoints()
    replies = await asyncio.gather(*(call_endpoint(record, "info") for record in records), return_exceptions=True)
    return {
        peer.session_id: record
        for reply in replies
        if isinstance(reply, dict)
        for record in [EndpointRecord.model_validate(reply)]
        for peer in record.sessions
    }


async def _request(method: str, path: str, body: dict[str, Any], params: dict[str, Any]) -> Any:
    summaries = await asyncio.to_thread(_summaries)
    online = await _online()
    if path == "/api/headless/sessions" and method == "GET":
        targets = str(params.get("targets") or "").split(",")
        selected = [_resolve(summaries, target) for target in targets if target]
        include_history = bool(params.get("history", False))
        candidates = selected if selected else summaries
        rows = []
        for summary in candidates:
            record = online.get(summary.id)
            if record is None and not include_history:
                continue
            if not params.get("include_archived") and summary.archived:
                continue
            if not params.get("include_children") and summary.parent_session_id is not None and not selected:
                continue
            if params.get("group") and summary.group != params["group"]:
                continue
            if params.get("dir") and Path(summary.work_dir).resolve() != Path(params["dir"]).resolve():
                continue
            row = asdict(summary)
            session = Session.load_meta(summary.id, work_dir=Path(summary.work_dir))
            status = offline_status(session)
            row.update(
                state=status.category,
                status=status.model_dump(mode="json"),
                pending=False,
                model=summary.model_config_name or summary.model_name,
                online=record is not None,
            )
            if record is not None:
                try:
                    row.update(await call_endpoint(record, "snapshot", session_id=summary.id, summary=True))
                except (OSError, ValueError, TimeoutError):
                    if not include_history:
                        continue
                    row["online"] = False
            states = params.get("state")
            if states and row["state"] not in states:
                continue
            rows.append(row)
        rows.sort(key=lambda row: ({"needs_you": 0, "working": 1, "idle": 2}[row["state"]], -row["updated_at"]))
        limit = int(params.get("limit") or 0)
        return {"sessions": rows[:limit] if limit > 0 else rows}

    prefix = "/api/headless/sessions/"
    if not path.startswith(prefix):
        raise ValueError("Unsupported process command")
    target, _, action = path[len(prefix) :].partition("/")
    summary = _resolve(summaries, target)
    record = online.get(summary.id)
    if action in {"output", "brief"}:
        if record is not None:
            with contextlib.suppress(OSError, ValueError, TimeoutError):
                return await call_endpoint(record, "snapshot", session_id=summary.id, **params)
        session = await asyncio.to_thread(Session.load, summary.id, work_dir=Path(summary.work_dir))
        return session_snapshot(session, turns=params.get("turns"), transcript=bool(params.get("transcript")))
    if record is None:
        raise ValueError(f"Session {summary.id} is offline; resume it explicitly with klaude -r")
    if action in {"send", "send-active"}:
        peer = PeerMessage(
            id=body.get("message_id") or uuid4().hex,
            recipient=summary.id,
            body=body["text"],
            sender_label=body.get("sender") or "external",
            reply_to=body.get("reply_to"),
        )
        receipt = await call_endpoint(
            record,
            "deliver",
            message=peer.model_dump(mode="json"),
            expected_operation_id=body.get("expected_operation_id"),
        )
        return {"session_id": summary.id, **receipt}
    if action == "tasks":
        return await call_endpoint(record, "tasks", session_id=summary.id, request=body)
    if action == "respond":
        return await call_endpoint(record, "respond", session_id=summary.id, response=body)
    if action == "control":
        return await call_endpoint(record, "control", session_id=summary.id, **body)
    if action in {"interrupt", "stop", "stop-children"}:
        return await call_endpoint(record, "stop-children" if action == "stop" else action, session_id=summary.id)
    raise ValueError("Unsupported process command")


def request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30,
) -> tuple[int, Any]:
    del timeout
    try:
        if method == "POST" and path == "/api/headless/run":
            return 200, spawn_process(json_body or {})
        return 200, asyncio.run(_request(method, path, json_body or {}, params or {}))
    except SessionTargetError as exc:
        return exc.status_code, {"detail": exc.detail}
    except (OSError, ValueError, TimeoutError) as exc:
        return 400, {"detail": str(exc)}


def spawn_process(payload: dict[str, Any]) -> dict[str, Any]:
    directory = Path(payload["work_dir"]).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"work_dir does not exist: {directory}")
    from klaude_code.config import load_config
    from klaude_code.protocol.sub_agent import get_all_names

    agent = payload.get("agent") or "main"
    if agent not in {"main", *get_all_names()}:
        raise ValueError(f"Unknown agent type: {agent}")
    config = load_config()
    model = payload.get("model")
    if model is not None and not config.iter_model_config_candidates(model):
        raise ValueError(f"Model is unavailable: {model}")
    name = payload.get("name")
    if name and any(item.name == name and not item.archived for item in _summaries()):
        raise ValueError(f"Name is already used: {name}")
    session_id = uuid4().hex
    root = Path.home() / ".klaude" / "run" / "spawn"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    input_path = root / f"{session_id}.json"
    ready_path = root / f"{session_id}.ready"
    fd = os.open(input_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump({**payload, "session_id": session_id}, file)
    log_path = root / f"{session_id}.log"
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(log_fd, "wb") as output:
        child = subprocess.Popen(
            [sys.executable, "-m", "klaude_code.cli.process_worker", str(input_path)],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            start_new_session=True,
            cwd=directory,
        )
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if ready_path.is_file():
                result = json.loads(ready_path.read_text())
                if result.get("error"):
                    raise ValueError(result["error"])
                return result
            if child.poll() is not None:
                raise ValueError(f"Agent process exited during startup; see {log_path}")
            time.sleep(0.05)
        # Startup may still succeed; preserve the ID so the caller can inspect it.
        raise ValueError(f"Agent startup timed out for {session_id}; see {log_path}")
    finally:
        if child.poll() is not None or ready_path.is_file():
            input_path.unlink(missing_ok=True)
            ready_path.unlink(missing_ok=True)
