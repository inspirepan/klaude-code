"""Standalone headless execution process; exits after owned work settles."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from klaude_code.app.process_lifecycle import cancel_on_termination
from klaude_code.config import load_config
from klaude_code.protocol import events
from klaude_code.protocol.message import UserInputPayload
from klaude_code.session import Session
from klaude_code.tui.client.local import LocalRuntimeClient


async def run_background(payload: dict[str, Any], ready: Callable[[dict[str, Any]], None]) -> None:
    with cancel_on_termination():
        await _run_background(payload, ready)


async def _run_background(payload: dict[str, Any], ready: Callable[[dict[str, Any]], None]) -> None:
    async def consume(_envelope: events.EventEnvelope) -> None:
        pass

    directory = Path(payload["work_dir"]).resolve()
    model = payload.get("model")
    agent_type = payload.get("agent") or "main"
    if model is None and agent_type != "main":
        preference = load_config().sub_agent_models.get(agent_type)
        if preference is not None:
            model = preference if isinstance(preference, str) else load_config().get_first_available_model(preference)
    session = Session.create(id=payload["session_id"], work_dir=directory)
    session.model_config_name = model
    session.model_from_role = payload.get("model") is None and agent_type != "main" and model is not None
    session.name = payload.get("name")
    session.group = payload.get("group")
    session.agent_type = agent_type
    session.spawn_kind = "headless"
    session.unattended = True
    session.ensure_meta_exists()
    client = LocalRuntimeClient(session.id, on_envelope=consume, work_dir=directory, model=model, unattended=True)
    try:
        await client.start()
        client.start_display()
        scheduler = client._scheduler
        endpoint = client._endpoint
        assert scheduler is not None and endpoint is not None
        await scheduler.spawn(
            session_id=session.id, prompt=UserInputPayload(text=payload["prompt"]), work_dir=directory
        )
        ready({"session_id": session.id, "name": session.name})
        while True:
            await asyncio.sleep(0.05)
            if client.has_running_tasks() or scheduler.has_scheduled_work():
                continue
            # Close admission without yielding, then recheck already accepted input.
            endpoint.accepting_input = False
            if client.has_running_tasks() or scheduler.has_scheduled_work():
                endpoint.accepting_input = True
                continue
            await client.command_agent().session.wait_for_flush()
            break
    finally:
        await client.close()


def main(input_path: Path) -> None:
    ready_path = input_path.with_suffix(".ready")
    published = False

    def publish(result: dict[str, Any]) -> None:
        nonlocal published
        temporary = ready_path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as file:
            json.dump(result, file)
        temporary.replace(ready_path)
        published = True

    try:
        payload = json.loads(input_path.read_text())
        asyncio.run(run_background(payload, publish))
    except BaseException as exc:
        if not published:
            publish({"error": str(exc) or type(exc).__name__})
        raise


if __name__ == "__main__":
    main(Path(sys.argv[1]))
