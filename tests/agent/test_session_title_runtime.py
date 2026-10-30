# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from klaude_code.agent.agent import Agent
from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.agent.runtime.config_ops import ModelSwitcher
from klaude_code.agent.runtime.llm import FallbackLLMClient, LLMClients, build_llm_clients
from klaude_code.agent.session_title import (
    _build_session_title_input,
    _normalize_session_title,
    generate_session_title,
)
from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.input_common import apply_config_defaults
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
    assert "<user_messages>" in rendered
    assert "[1] first request" in rendered
    assert "[2] (latest) latest request about src/app.py" in rendered
    assert "main task of the whole conversation" in rendered.lower()
    assert "never changes an existing one" in rendered.lower()
    assert "return it unchanged" in rendered.lower()
    assert "be specific" in rendered.lower()
    assert "reflect user intent" in rendered.lower()
    assert "4-10 chinese characters" in rendered.lower()
    assert "never exceed 40 characters" in rendered.lower()
    assert "omit repository names" in rendered.lower()
    assert "<previous_title>" in rendered
    assert "Existing title" in rendered
    assert "assistant" not in rendered.lower()
    assert client.calls[0].system is not None
    assert "same language" in client.calls[0].system.lower()
    assert "not the latest message" in client.calls[0].system.lower()


def test_build_session_title_input_marks_only_latest_message() -> None:
    rendered = message.join_text_parts(
        _build_session_title_input(["重构标题生成", "  ", "提交代码"], previous_title="重构标题生成").pop().parts
    )

    assert "<previous_title>\n重构标题生成\n</previous_title>" in rendered
    assert "[1] 重构标题生成\n\n[2] (latest) 提交代码" in rendered
    assert rendered.count("(latest)") == 1


def test_build_session_title_input_omits_previous_title_block_when_absent() -> None:
    rendered = message.join_text_parts(_build_session_title_input(["修复终端标题截断"]).pop().parts)

    assert "<previous_title>" not in rendered
    assert "[1] (latest) 修复终端标题截断" in rendered


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


@pytest.mark.parametrize(
    ("error", "fallback"),
    [
        ("insufficient_quota", True),
        ("invalid_request_error: invalid parameter", False),
        ("context length exceeded: insufficient_quota", False),
    ],
)
def test_title_fallback_is_classified_and_isolated(monkeypatch: pytest.MonkeyPatch, error: str, fallback: bool) -> None:
    provider = ProviderConfig(
        provider_name="test-provider",
        protocol=llm_param.LLMClientProtocol.OPENAI,
        api_key="test-key",
        model_list=[ModelConfig(model_name=f"model-{i}", model_id=f"model-{i}") for i in range(4)],
    )
    config = Config(provider_list=[provider], main_model=[f"model-{i}" for i in range(4)])
    client = build_llm_clients(config).main
    assert isinstance(client, FallbackLLMClient)
    calls: list[str] = []

    class _Client(_FakeLLMClient):
        async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
            apply_config_defaults(param, self.get_llm_config())
            calls.append(param.model_id or "")
            return await super().call(param)

    def _create(llm_config: llm_param.LLMConfigParameter) -> LLMClientABC:
        items: list[message.LLMStreamItem] = (
            [message.AssistantMessage(parts=[message.TextPart(text="标题")])]
            if llm_config.model_id == "model-3"
            else [message.StreamErrorItem(error=error)]
        )
        return _Client(items, config=llm_config)

    monkeypatch.setattr("klaude_code.agent.runtime.llm.create_llm_client", _create)
    monkeypatch.setattr("klaude_code.agent.runtime.llm.load_config", lambda: config)
    if fallback:
        assert asyncio.run(generate_session_title(llm_client=client, user_messages=["请求"])) == "标题"
        assert calls == ["model-0", "model-1", "model-2", "model-3"]
    else:
        with pytest.raises(RuntimeError, match=error):
            asyncio.run(generate_session_title(llm_client=client, user_messages=["请求"]))
        assert calls == ["model-0"] * 3
    assert client.active_candidate.model_name == "model-0"
    assert len(client._clients) == (4 if fallback else 1)


def test_title_fallback_sends_each_candidate_model_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ProviderConfig(
        provider_name="test-provider",
        protocol=llm_param.LLMClientProtocol.OPENAI,
        api_key="test-key",
        model_list=[ModelConfig(model_name=name, model_id=name) for name in ("first", "second")],
    )
    config = Config(provider_list=[provider], main_model=["first", "second"])
    models: list[str] = []

    async def create(**kwargs: Any) -> Any:
        models.append(kwargs["model"])
        raise httpx.ConnectError("insufficient_quota" if kwargs["model"] == "first" else "invalid request")

    monkeypatch.setattr(
        "klaude_code.llm.openai_compatible.client.openai.AsyncOpenAI",
        lambda **_kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    monkeypatch.setattr("klaude_code.llm.openai_compatible.client.create_async_http_client", lambda: None)
    monkeypatch.setattr("klaude_code.agent.runtime.llm.load_config", lambda: config)
    client = build_llm_clients(config).main

    with pytest.raises(RuntimeError, match="invalid request"):
        asyncio.run(generate_session_title(llm_client=client, user_messages=["请求"]))

    assert models == ["first", "second", "second", "second"]


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
            ModelConfig(model_name="fast-backup", model_id="fast-backup-id"),
            ModelConfig(model_name="compact-model", model_id="compact-model-id"),
        ],
    )
    config = Config(
        provider_list=[provider],
        main_model="main-model",
        fast_model=["missing-fast-model", "fast-model", "fast-backup"],
        compact_model=["missing-compact-model", "compact-model"],
    )

    created_clients: list[llm_param.LLMConfigParameter] = []

    def _create_client(llm_config: llm_param.LLMConfigParameter) -> LLMClientABC:
        created_clients.append(llm_config)
        return _FakeLLMClient([], config=llm_config)

    monkeypatch.setattr(
        "klaude_code.agent.runtime.llm.create_llm_client",
        _create_client,
    )

    clients = build_llm_clients(config)

    assert clients.main.model_name == "main-model-id"
    assert clients.fast is not None
    assert clients.fast.model_name == "fast-model-id"
    assert isinstance(clients.fast, FallbackLLMClient)
    assert [candidate.model_name for candidate in clients.fast.candidates] == ["fast-model", "fast-backup"]
    assert clients.compact is not None
    assert clients.compact.model_name == "compact-model-id"
    assert created_clients == []

    async def _warm_concurrently() -> None:
        await asyncio.gather(clients.warmup(), clients.warmup())

    asyncio.run(_warm_concurrently())
    assert [client.model_id for client in created_clients] == ["main-model-id"]


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

    clients = build_llm_clients(config)

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == [
        "gpt-5.4@openai",
        "gpt-5.4@openrouter",
        "sonnet@openrouter",
    ]
    assert clients.main_model_alias == "gpt-5.4 > sonnet"


def test_build_llm_clients_uses_compact_model_fallback_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = [
        ProviderConfig(
            provider_name="openai",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="openai-key",
            model_list=[ModelConfig(model_name="compact", model_id="openai/compact")],
        ),
        ProviderConfig(
            provider_name="openrouter",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="openrouter-key",
            model_list=[
                ModelConfig(model_name="compact", model_id="openrouter/compact"),
                ModelConfig(model_name="cheap", model_id="openrouter/cheap"),
            ],
        ),
    ]
    config = Config(
        provider_list=providers,
        main_model="compact@openai",
        compact_model=["compact", "cheap"],
    )

    def _create_client(llm_config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return _FakeLLMClient([], config=llm_config)

    monkeypatch.setattr(
        "klaude_code.agent.runtime.llm.create_llm_client",
        _create_client,
    )

    clients = build_llm_clients(config)

    assert isinstance(clients.compact, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.compact.candidates] == [
        "compact@openai",
        "compact@openrouter",
        "cheap@openrouter",
    ]


def test_build_llm_clients_model_override_keeps_main_fallback_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = [
        ProviderConfig(
            provider_name="chatgpt",
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
        main_model=["gpt-5.5@chatgpt", "gpt-5.5@openai", "opus@ant-gw"],
    )

    def _create_client(llm_config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return _FakeLLMClient([], config=llm_config)

    monkeypatch.setattr(
        "klaude_code.agent.runtime.llm.create_llm_client",
        _create_client,
    )

    clients = build_llm_clients(config, model_override="gpt-5.5@chatgpt")

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == [
        "gpt-5.5@chatgpt",
        "gpt-5.5@openai",
        "opus@ant-gw",
    ]
    assert clients.main_model_alias == "gpt-5.5@chatgpt > gpt-5.5@openai > opus@ant-gw"


def test_session_model_config_restore_keeps_main_fallback_suffix(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    providers = [
        ProviderConfig(
            provider_name="chatgpt",
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
        main_model=["gpt-5.5@chatgpt", "gpt-5.5@openai", "opus@ant-gw"],
    )
    template_client = _FakeLLMClient([], config=config.get_model_config("opus@ant-gw"))
    session = Session.create(work_dir=tmp_path)
    session.model_config_name = "gpt-5.5@chatgpt"

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
        on_child_task_state_change=_noop_child_task_state_change,
        ensure_session_actor=lambda _sid: cast_any(actor),
        get_session_actor=lambda _sid: None,
        get_session_actor_for_operation=lambda _op: None,
        list_session_actors=lambda: [],
        register_task=_noop_register_task,
        remove_task=_noop_remove_task,
        request_user_interaction=_noop_request_user_interaction,
    )

    clients = handler._ensure_session_llm_clients(session).clients

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == [
        "gpt-5.5@chatgpt",
        "gpt-5.5@openai",
        "opus@ant-gw",
    ]
    assert clients.main_model_alias == "gpt-5.5@chatgpt > gpt-5.5@openai > opus@ant-gw"


def test_model_switcher_keeps_main_fallback_suffix_after_selection(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    providers = [
        ProviderConfig(
            provider_name="chatgpt",
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
        main_model=["gpt-5.5@chatgpt", "gpt-5.5@openai", "opus@ant-gw"],
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
        switcher.change_model(agent, model_name="gpt-5.5@chatgpt", save_as_default=False)
    )

    assert selected_model == "gpt-5.5@chatgpt"
    assert llm_config.provider_name == "chatgpt"
    assert agent.session.model_config_name == "gpt-5.5@chatgpt"
    assert isinstance(agent.profile.llm_client, FallbackLLMClient)
    assert [candidate.selector for candidate in agent.profile.llm_client.candidates] == [
        "gpt-5.5@chatgpt",
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
