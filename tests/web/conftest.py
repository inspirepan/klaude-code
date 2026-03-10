from __future__ import annotations

import asyncio
import shutil
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar, cast

import pytest
from fastapi.testclient import TestClient

from klaude_code.core.agent import runtime_llm as agent_runtime
from klaude_code.core.agent.runtime_llm import LLMClients
from klaude_code.core.control.event_bus import EventBus
from klaude_code.core.control.runtime_facade import RuntimeFacade
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import llm_param, message, model
from klaude_code.session.session import close_default_store
from klaude_code.web.app import create_app
from klaude_code.web.interaction import WebInteractionHandler
from klaude_code.web.state import WebAppState

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class ScriptedLLMStream(LLMStreamABC):
    def __init__(self, items: list[message.LLMStreamItem], *, delay_s: float = 0.0) -> None:
        self._items = items
        self._delay_s = delay_s
        self._partial_parts: list[message.Part] = []
        self._response_id: str | None = None
        self._final_message: message.AssistantMessage | None = None

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for item in self._items:
            if self._delay_s > 0:
                await asyncio.sleep(self._delay_s)
            if isinstance(item, message.ThinkingTextDelta):
                self._response_id = item.response_id
                self._partial_parts.append(message.ThinkingTextPart(text=item.content))
            elif isinstance(item, message.AssistantTextDelta):
                self._response_id = item.response_id
                self._partial_parts.append(message.TextPart(text=item.content))
            elif isinstance(item, message.AssistantMessage):
                self._final_message = item
            yield item

    def get_partial_message(self) -> message.AssistantMessage | None:
        if self._final_message is not None:
            return self._final_message
        if not self._partial_parts:
            return None
        return message.AssistantMessage(
            parts=list(self._partial_parts),
            response_id=self._response_id,
            stop_reason="aborted",
        )


class FakeLLMClient(LLMClientABC):
    def __init__(self) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="fake-model",
            )
        )
        self._responses: list[tuple[list[message.LLMStreamItem], float]] = []

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del config
        return cls()

    def enqueue(self, *items: message.LLMStreamItem, delay_s: float = 0.0) -> None:
        self._responses.append((list(items), delay_s))

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        del param
        if not self._responses:
            raise RuntimeError("FakeLLMClient has no queued response")
        items, delay_s = self._responses.pop(0)
        return ScriptedLLMStream(items, delay_s=delay_s)


@dataclass
class AppEnv:
    client: TestClient
    runtime: RuntimeFacade
    event_bus: EventBus
    fake_llm: FakeLLMClient
    interaction_handler: WebInteractionHandler
    work_dir: Path
    home_dir: Path

    def create_session(self, work_dir: Path | None = None) -> str:
        payload: dict[str, str] = {}
        if work_dir is not None:
            payload["work_dir"] = str(work_dir)
        response = self.client.post("/api/sessions", json=payload)
        assert response.status_code == 200
        return str(response.json()["session_id"])


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home_dir))

    def _patched_home(cls: type[Path]) -> Path:
        del cls
        return home_dir

    def _identity_clone(client: Any) -> Any:
        return client

    monkeypatch.setattr(Path, "home", cast(Any, classmethod(_patched_home)))
    monkeypatch.setattr(agent_runtime, "clone_llm_client", _identity_clone)

    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    fake_llm = FakeLLMClient()
    holder: dict[str, RuntimeFacade | EventBus | WebInteractionHandler] = {}

    async def _state_initializer() -> WebAppState:
        event_bus = EventBus()
        runtime = RuntimeFacade(event_bus, LLMClients(main=fake_llm, main_model_alias="fake"), runtime_kind="web")
        interaction_handler = WebInteractionHandler()
        holder["event_bus"] = event_bus
        holder["runtime"] = runtime
        holder["interaction_handler"] = interaction_handler
        return WebAppState(
            runtime=runtime,
            event_bus=event_bus,
            interaction_handler=interaction_handler,
            work_dir=work_dir,
            home_dir=home_dir,
        )

    async def _state_shutdown(state: WebAppState) -> None:
        await state.runtime.stop()
        await close_default_store()

    app = create_app(
        work_dir=work_dir,
        home_dir=home_dir,
        state_initializer=_state_initializer,
        state_shutdown=_state_shutdown,
    )

    with TestClient(app) as client:
        runtime = holder.get("runtime")
        event_bus = holder.get("event_bus")
        interaction_handler = holder.get("interaction_handler")
        assert isinstance(runtime, RuntimeFacade)
        assert isinstance(event_bus, EventBus)
        assert isinstance(interaction_handler, WebInteractionHandler)

        yield AppEnv(
            client=client,
            runtime=runtime,
            event_bus=event_bus,
            fake_llm=fake_llm,
            interaction_handler=interaction_handler,
            work_dir=work_dir,
            home_dir=home_dir,
        )

    # Explicitly clean up temporary session artifacts produced by each test.
    shutil.rmtree(home_dir / ".klaude", ignore_errors=True)


def usage(
    *,
    input_tokens: int = 10,
    output_tokens: int = 5,
    cached_tokens: int = 0,
) -> model.Usage:
    return model.Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        context_size=input_tokens + output_tokens,
        context_limit=200_000,
        model_name="fake-model",
        provider="test",
    )


def collect_events_until(websocket: Any, target_type: str, max_events: int = 200) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for _ in range(max_events):
        event = websocket.receive_json()
        events.append(event)
        if event.get("event_type") == target_type:
            return events
    raise AssertionError(f"Did not receive event type: {target_type}")


def wait_for_event(websocket: Any, event_type: str, max_events: int = 200) -> dict[str, Any]:
    for _ in range(max_events):
        event = websocket.receive_json()
        if event.get("event_type") == event_type:
            return event
    raise AssertionError(f"Did not receive event type: {event_type}")


def consume_ws_handshake(websocket: Any) -> dict[str, Any]:
    """Read the connection_info frame and usage snapshot. Return the usage snapshot."""
    connection_info = websocket.receive_json()
    assert connection_info["type"] == "connection_info"
    usage_snapshot = websocket.receive_json()
    assert usage_snapshot["event_type"] == "usage.snapshot"
    return usage_snapshot


def extract_text(events: list[dict[str, Any]]) -> str:
    return "".join(
        str(event.get("event", {}).get("content", ""))
        for event in events
        if event.get("event_type") == "assistant.text.delta"
    )
