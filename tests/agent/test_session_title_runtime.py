# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest

from klaude_code.agent.agent import Agent
from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.agent.runtime.config_ops import ModelSwitcher
from klaude_code.agent.runtime.llm import FallbackLLMClient, LLMClients, build_llm_clients
from klaude_code.agent.session_title import _normalize_session_title, generate_session_title
from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import llm_param, message
from klaude_code.session.session import Session


class _FakeStream(LLMStreamABC):
    def __init__(self, items: list[message.LLMStreamItem]) -> None:
        self._items = items

    async def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        for item in self._items:
            yield item

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class _FakeLLMClient(LLMClientABC):
    def __init__(
        self, items: list[message.LLMStreamItem], *, config: llm_param.LLMConfigParameter | None = None
    ) -> None:
        super().__init__(
            config
            or llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="fake-compact",
            )
        )
        self.items = items
        self.calls: list[llm_param.LLMCallParameter] = []

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del config
        return cls([])

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self.calls.append(param)
        return _FakeStream(self.items)


class _SequencedFakeLLMClient(LLMClientABC):
    def __init__(self, responses: list[list[message.LLMStreamItem]]) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="fake-compact",
            )
        )
        self._responses = responses
        self.calls: list[llm_param.LLMCallParameter] = []

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del config
        return cls([])

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self.calls.append(param)
        index = len(self.calls) - 1
        return _FakeStream(self._responses[index])


def test_generate_session_title_uses_only_user_messages() -> None:
    client = _FakeLLMClient(
        [
            message.AssistantMessage(
                parts=[message.TextPart(text='  "Session titles — Refine prompts"  ')], stop_reason="stop"
            )
        ]
    )

    title = asyncio.run(
        generate_session_title(
            llm_client=client,
            user_messages=["first request", "latest request about src/app.py"],
            previous_title="Existing title",
        )
    )

    assert title == "Session titles — Refine prompts"
    assert len(client.calls) == 1
    rendered = message.join_text_parts(client.calls[0].input[0].parts)
    assert "<previous_user_messages>" in rendered
    assert "<current_user_message>" in rendered
    assert "first request" in rendered
    assert "latest request about src/app.py" in rendered
    assert "be specific" in rendered.lower()
    assert "reflect user intent" in rendered.lower()
    assert "previous title" in rendered.lower()
    assert "<previous_title>" in rendered
    assert "Existing title" in rendered
    assert "assistant" not in rendered.lower()
    assert client.calls[0].system is not None
    assert "same language" in client.calls[0].system.lower()


def test_generate_session_title_retries_up_to_three_attempts() -> None:
    client = _SequencedFakeLLMClient(
        [
            [message.StreamErrorItem(error="temporary failure")],
            [message.StreamErrorItem(error="temporary failure")],
            [message.AssistantMessage(parts=[message.TextPart(text="修复 session title 重试")], stop_reason="stop")],
        ]
    )

    title = asyncio.run(generate_session_title(llm_client=client, user_messages=["给标题生成加重试"]))

    assert title == "修复 session title 重试"
    assert len(client.calls) == 3


def test_normalize_session_title_canonicalizes_separator() -> None:
    assert _normalize_session_title('  "Session titles | Refine prompts"  ') == "Session titles — Refine prompts"


def test_build_llm_clients_uses_fast_model_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ProviderConfig(
        provider_name="test-provider",
        protocol=llm_param.LLMClientProtocol.OPENAI,
        api_key="test-key",
        model_list=[
            ModelConfig(model_name="main-model", model_id="main-model-id"),
            ModelConfig(model_name="fast-model", model_id="fast-model-id"),
            ModelConfig(model_name="compact-model", model_id="compact-model-id"),
        ],
    )
    config = Config(
        provider_list=[provider],
        main_model="main-model",
        fast_model=["missing-fast-model", "fast-model"],
        compact_model=["missing-compact-model", "compact-model"],
    )

    def _create_client(llm_config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return _FakeLLMClient([], config=llm_config)

    monkeypatch.setattr(
        "klaude_code.agent.runtime.llm.create_llm_client",
        _create_client,
    )

    clients = build_llm_clients(config, skip_sub_agents=True)

    assert clients.main.model_name == "main-model-id"
    assert clients.fast is not None
    assert clients.fast.model_name == "fast-model-id"
    assert clients.compact is not None
    assert clients.compact.model_name == "compact-model-id"


def test_build_llm_clients_uses_main_model_fallback_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = [
        ProviderConfig(
            provider_name="openai",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="openai-key",
            model_list=[ModelConfig(model_name="gpt-5.4", model_id="openai/gpt-5.4")],
        ),
        ProviderConfig(
            provider_name="openrouter",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="openrouter-key",
            model_list=[
                ModelConfig(model_name="gpt-5.4", model_id="openrouter/gpt-5.4"),
                ModelConfig(model_name="sonnet", model_id="openrouter/sonnet"),
            ],
        ),
    ]
    config = Config(
        provider_list=providers,
        main_model=["gpt-5.4", "sonnet"],
    )

    def _create_client(llm_config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return _FakeLLMClient([], config=llm_config)

    monkeypatch.setattr(
        "klaude_code.agent.runtime.llm.create_llm_client",
        _create_client,
    )

    clients = build_llm_clients(config, skip_sub_agents=True)

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == [
        "gpt-5.4@openai",
        "gpt-5.4@openrouter",
        "sonnet@openrouter",
    ]
    assert clients.main_model_alias == "gpt-5.4 > sonnet"


def test_build_llm_clients_model_override_keeps_main_fallback_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = [
        ProviderConfig(
            provider_name="codex",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="codex-key",
            model_list=[ModelConfig(model_name="gpt-5.5", model_id="gpt-5.5")],
        ),
        ProviderConfig(
            provider_name="openai",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="openai-key",
            model_list=[ModelConfig(model_name="gpt-5.5", model_id="openai/gpt-5.5")],
        ),
        ProviderConfig(
            provider_name="ant-gw",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="anthropic-key",
            model_list=[ModelConfig(model_name="opus", model_id="anthropic/opus")],
        ),
    ]
    config = Config(
        provider_list=providers,
        main_model=["gpt-5.5@codex", "gpt-5.5@openai", "opus@ant-gw"],
    )

    def _create_client(llm_config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return _FakeLLMClient([], config=llm_config)

    monkeypatch.setattr(
        "klaude_code.agent.runtime.llm.create_llm_client",
        _create_client,
    )

    clients = build_llm_clients(config, model_override="gpt-5.5@codex", skip_sub_agents=True)

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == [
        "gpt-5.5@codex",
        "gpt-5.5@openai",
        "opus@ant-gw",
    ]
    assert clients.main_model_alias == "gpt-5.5@codex > gpt-5.5@openai > opus@ant-gw"


def test_session_model_config_restore_keeps_main_fallback_suffix(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    providers = [
        ProviderConfig(
            provider_name="codex",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="codex-key",
            model_list=[ModelConfig(model_name="gpt-5.5", model_id="gpt-5.5")],
        ),
        ProviderConfig(
            provider_name="openai",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="openai-key",
            model_list=[ModelConfig(model_name="gpt-5.5", model_id="openai/gpt-5.5")],
        ),
        ProviderConfig(
            provider_name="ant-gw",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="anthropic-key",
            model_list=[ModelConfig(model_name="opus", model_id="anthropic/opus")],
        ),
    ]
    config = Config(
        provider_list=providers,
        main_model=["gpt-5.5@codex", "gpt-5.5@openai", "opus@ant-gw"],
    )
    template_client = _FakeLLMClient([], config=config.get_model_config("opus@ant-gw"))
    session = Session.create(work_dir=tmp_path)
    session.model_config_name = "gpt-5.5@codex"

    class _FakeSessionActor:
        def __init__(self) -> None:
            self.clients: LLMClients | None = None

        def get_llm_clients(self) -> LLMClients | None:
            return self.clients

        def set_llm_clients(self, clients: LLMClients) -> None:
            self.clients = clients

    actor = _FakeSessionActor()
    monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.load_config", lambda: config)

    handler = AgentOperationHandler(
        emit_event=_noop_emit,
        llm_clients=LLMClients(main=template_client),
        model_profile_provider=cast_any(object()),
        sub_agent_manager=cast_any(object()),
        on_child_task_state_change=_noop_child_task_state_change,
        ensure_session_actor=lambda _sid: cast_any(actor),
        get_session_actor=lambda _sid: None,
        get_session_actor_for_operation=lambda _op: None,
        list_session_actors=lambda: [],
        register_task=_noop_register_task,
        remove_task=_noop_remove_task,
        request_user_interaction=_noop_request_user_interaction,
    )

    clients = handler._ensure_session_llm_clients(session)

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == [
        "gpt-5.5@codex",
        "gpt-5.5@openai",
        "opus@ant-gw",
    ]
    assert clients.main_model_alias == "gpt-5.5@codex > gpt-5.5@openai > opus@ant-gw"


def test_model_switcher_keeps_main_fallback_suffix_after_selection(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    providers = [
        ProviderConfig(
            provider_name="codex",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="codex-key",
            model_list=[ModelConfig(model_name="gpt-5.5", model_id="gpt-5.5")],
        ),
        ProviderConfig(
            provider_name="openai",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="openai-key",
            model_list=[ModelConfig(model_name="gpt-5.5", model_id="openai/gpt-5.5")],
        ),
        ProviderConfig(
            provider_name="ant-gw",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="anthropic-key",
            model_list=[ModelConfig(model_name="opus", model_id="anthropic/opus")],
        ),
    ]
    config = Config(
        provider_list=providers,
        main_model=["gpt-5.5@codex", "gpt-5.5@openai", "opus@ant-gw"],
    )

    def _create_client(llm_config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return _FakeLLMClient([], config=llm_config)

    class _FakeProfileProvider:
        def build_profile(
            self,
            llm_client: LLMClientABC,
            sub_agent_type: object = None,
            *,
            work_dir: Path,
        ) -> AgentProfile:
            del sub_agent_type
            del work_dir
            return AgentProfile(llm_client=llm_client, system_prompt=None, tools=[], attachments=[])

    monkeypatch.setattr("klaude_code.agent.runtime.config_ops.load_config", lambda: config)
    monkeypatch.setattr("klaude_code.agent.runtime.llm.create_llm_client", _create_client)

    initial_client = _FakeLLMClient([], config=config.get_model_config("opus@ant-gw"))
    agent = Agent(
        session=Session.create(work_dir=tmp_path),
        profile=AgentProfile(llm_client=initial_client, system_prompt=None, tools=[], attachments=[]),
    )

    switcher = ModelSwitcher(_FakeProfileProvider())
    llm_config, selected_model = asyncio.run(
        switcher.change_model(agent, model_name="gpt-5.5@codex", save_as_default=False)
    )

    assert selected_model == "gpt-5.5@codex"
    assert llm_config.provider_name == "codex"
    assert agent.session.model_config_name == "gpt-5.5@codex"
    assert isinstance(agent.profile.llm_client, FallbackLLMClient)
    assert [candidate.selector for candidate in agent.profile.llm_client.candidates] == [
        "gpt-5.5@codex",
        "gpt-5.5@openai",
        "opus@ant-gw",
    ]


def test_refresh_session_title_prefers_fast_client(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        main_client = _FakeLLMClient([])
        compact_client = _FakeLLMClient([])
        fast_client = _FakeLLMClient(
            [message.AssistantMessage(parts=[message.TextPart(text="最新标题")], stop_reason="stop")]
        )
        emitted: list[Any] = []

        async def _emit(event: Any) -> None:
            emitted.append(event)

        handler = AgentOperationHandler(
            emit_event=_emit,
            llm_clients=LLMClients(main=main_client, fast=fast_client, compact=compact_client),
            model_profile_provider=cast_any(object()),
            sub_agent_manager=cast_any(object()),
            on_child_task_state_change=_noop_child_task_state_change,
            ensure_session_actor=_unexpected_session_actor,
            get_session_actor=lambda _sid: None,
            get_session_actor_for_operation=lambda _op: None,
            list_session_actors=lambda: [],
            register_task=_noop_register_task,
            remove_task=_noop_remove_task,
            request_user_interaction=_noop_request_user_interaction,
        )
        session = Session(work_dir=tmp_path)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("继续优化标题生成"))])

        def _fake_get_clients(_sid: str) -> LLMClients:
            return LLMClients(main=main_client, fast=fast_client, compact=compact_client)

        monkeypatch.setattr(handler, "get_session_llm_clients", _fake_get_clients)

        await session.wait_for_flush()
        await handler._refresh_session_title(
            session,
            user_messages_snapshot=list(session.user_messages),
            previous_title_snapshot=None,
        )

        assert len(fast_client.calls) == 1
        assert len(compact_client.calls) == 0
        assert len(main_client.calls) == 0
        assert session.title == "最新标题"
        assert emitted[-1].title == "最新标题"

    asyncio.run(_test())


def test_schedule_session_title_refresh_runs_in_background(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        client = _FakeLLMClient([])
        handler = AgentOperationHandler(
            emit_event=_noop_emit,
            llm_clients=LLMClients(main=client, fast=client, compact=client),
            model_profile_provider=cast_any(object()),
            sub_agent_manager=cast_any(object()),
            on_child_task_state_change=_noop_child_task_state_change,
            ensure_session_actor=_unexpected_session_actor,
            get_session_actor=lambda _sid: None,
            get_session_actor_for_operation=lambda _op: None,
            list_session_actors=lambda: [],
            register_task=_noop_register_task,
            remove_task=_noop_remove_task,
            request_user_interaction=_noop_request_user_interaction,
        )
        session = Session(work_dir=tmp_path)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("先分析 session 标题"))])
        session.update_title("已有标题")
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("继续优化标题"))])

        started = asyncio.Event()
        release = asyncio.Event()

        async def _fake_refresh(
            _session: Session, *, user_messages_snapshot: list[str], previous_title_snapshot: str | None
        ) -> None:
            assert user_messages_snapshot == ["先分析 session 标题", "继续优化标题"]
            assert previous_title_snapshot == "已有标题"
            started.set()
            await release.wait()

        monkeypatch.setattr(handler, "_refresh_session_title", _fake_refresh)
        handler._schedule_session_title_refresh(session)

        await asyncio.wait_for(started.wait(), timeout=1)
        assert session.id in handler._title_refresh_tasks
        assert not handler._title_refresh_tasks[session.id].done()

        release.set()
        await handler._title_refresh_tasks[session.id]

    asyncio.run(_test())


async def _noop_emit(_event: Any) -> None:
    return None


async def _noop_request_user_interaction(_request: Any) -> Any:
    raise RuntimeError("should not be called")


def _noop_child_task_state_change(_session_id: str, _task_id: str, _active: bool) -> None:
    return None


def _unexpected_session_actor(_sid: str) -> Any:
    raise RuntimeError("should not be called")


def _noop_register_task(_session_id: str, _operation_id: str, _task_id: str, _task: asyncio.Task[None]) -> None:
    return None


def _noop_remove_task(_session_id: str, _task_id: str) -> None:
    return None


def cast_any(value: object) -> Any:
    return value
