"""Characterization tests for pure / small-contract helpers on TaskExecutor.

Locks in CURRENT observable behavior of:
- ``TaskExecutor._has_tool`` (membership over profile.tools by ToolSchema.name).
- ``TaskExecutor._developer_message_key`` (attachment dedup key derivation).
- ``TaskExecutor._fallback_model`` vs ``TaskExecutor._fallback_compact_model``
  observable effects on ctx.profile / ctx.tool_registry / appended history /
  returned event, including the no-fallback (returns None) path.
- ``is_fallbackable_llm_error`` markers.

We call ``_fallback_model`` / ``_fallback_compact_model`` directly on a minimally
constructed TaskExecutor instead of running a full task, to isolate their
observable contract. These tests assert what the code currently DOES.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import override

import pytest

from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.model_fallback import is_fallbackable_llm_error
from klaude_code.agent.runtime.llm import FallbackLLMClient
from klaude_code.agent.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.config.config import ModelConfigCandidate
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import events, llm_param, message
from klaude_code.session.session import Session
from klaude_code.tool.core.context import build_todo_context


def _tool_schema(name: str) -> llm_param.ToolSchema:
    return llm_param.ToolSchema(name=name, type="function", description=f"{name} tool", parameters={})


def _config(provider: str, model_id: str) -> llm_param.LLMConfigParameter:
    return llm_param.LLMConfigParameter(
        provider_name=provider,
        protocol=llm_param.LLMClientProtocol.OPENAI,
        model_id=model_id,
    )


class _StubClient(LLMClientABC):
    """Non-fallbackable LLM client (used to verify the None-fallback path)."""

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:  # pragma: no cover - never called
        raise NotImplementedError


def _build_executor(
    *,
    tmp_path: Path,
    llm_client: LLMClientABC,
    tools: list[llm_param.ToolSchema] | None = None,
    compact_llm_client: LLMClientABC | None = None,
) -> tuple[TaskExecutor, TaskExecutionContext, Session]:
    session = Session.create(work_dir=tmp_path)
    session_ctx = SessionContext(
        session_id=session.id,
        work_dir=tmp_path,
        get_conversation_history=session.get_llm_history,
        append_history=session.append_history,
        file_tracker=session.file_tracker,
        file_change_summary=session.file_change_summary,
        todo_context=build_todo_context(session),
        run_subtask=None,
        request_user_interaction=None,
    )
    profile = AgentProfile(
        llm_client=llm_client,
        system_prompt="system prompt",
        tools=tools or [],
        attachments=[],
    )
    ctx = TaskExecutionContext(
        session=session,
        session_ctx=session_ctx,
        profile=profile,
        tool_registry={},
        sub_agent_state=None,
        compact_llm_client=compact_llm_client,
    )
    return TaskExecutor(ctx), ctx, session


def _fallback_client() -> FallbackLLMClient:
    return FallbackLLMClient(
        [
            ModelConfigCandidate(
                selector="gpt-5.5@openai",
                model_name="gpt-5.5",
                provider="openai",
                llm_config=_config("openai", "gpt-5.5"),
            ),
            ModelConfigCandidate(
                selector="gpt-5.4@openrouter",
                model_name="gpt-5.4",
                provider="openrouter",
                llm_config=_config("openrouter", "gpt-5.4"),
            ),
        ]
    )


# ---------------------------------------------------------------------------
# _has_tool
# ---------------------------------------------------------------------------


def test_has_tool_matches_by_schema_name(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    executor, _ctx, _session = _build_executor(
        tmp_path=tmp_path,
        llm_client=_StubClient(_config("openai", "m")),
        tools=[_tool_schema("Bash"), _tool_schema("Read")],
    )
    assert executor._has_tool("Bash") is True  # pyright: ignore[reportPrivateUsage]
    assert executor._has_tool("Read") is True  # pyright: ignore[reportPrivateUsage]
    assert executor._has_tool("Write") is False  # pyright: ignore[reportPrivateUsage]
    # Case-sensitive membership.
    assert executor._has_tool("bash") is False  # pyright: ignore[reportPrivateUsage]


def test_has_tool_false_when_no_tools(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    executor, _ctx, _session = _build_executor(
        tmp_path=tmp_path,
        llm_client=_StubClient(_config("openai", "m")),
        tools=[],
    )
    assert executor._has_tool("Bash") is False  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# _developer_message_key (attachment dedup key)
# ---------------------------------------------------------------------------


def test_developer_message_key_ignores_id_created_at_response_id() -> None:
    a = message.DeveloperMessage(parts=[message.TextPart(text="reminder body")], id="id-a", response_id="resp-a")
    b = message.DeveloperMessage(parts=[message.TextPart(text="reminder body")], id="id-b", response_id="resp-b")
    # Distinct ids/response_ids/timestamps, but same content -> same dedup key.
    assert a.id != b.id
    assert TaskExecutor._developer_message_key(a) == TaskExecutor._developer_message_key(b)  # pyright: ignore[reportPrivateUsage]


def test_developer_message_key_differs_on_content() -> None:
    a = message.DeveloperMessage(parts=[message.TextPart(text="one")])
    b = message.DeveloperMessage(parts=[message.TextPart(text="two")])
    assert TaskExecutor._developer_message_key(a) != TaskExecutor._developer_message_key(b)  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# _fallback_model
# ---------------------------------------------------------------------------


def test_fallback_model_returns_none_for_non_fallback_client(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    executor, _ctx, session = _build_executor(
        tmp_path=tmp_path,
        llm_client=_StubClient(_config("openai", "m")),
    )
    before = len(session.conversation_history)
    result = executor._fallback_model("insufficient_quota")  # pyright: ignore[reportPrivateUsage]
    assert result is None
    # No history mutation on the no-fallback path.
    assert len(session.conversation_history) == before


def test_fallback_model_returns_none_for_overflow_error(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    executor, _ctx, _session = _build_executor(tmp_path=tmp_path, llm_client=_fallback_client())
    # Context-overflow errors are NOT fallbackable.
    result = executor._fallback_model("prompt is too long")  # pyright: ignore[reportPrivateUsage]
    assert result is None


def test_fallback_model_advances_candidate_and_emits_warning(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home

    async def _test() -> None:
        client = _fallback_client()
        executor, ctx, session = _build_executor(
            tmp_path=tmp_path,
            llm_client=client,
            tools=[_tool_schema("Bash")],
        )
        original_profile = ctx.profile
        result = executor._fallback_model("insufficient_quota: credits exhausted")  # pyright: ignore[reportPrivateUsage]
        assert result is not None
        new_profile, event = result

        # No apply_llm_client_change -> a fresh AgentProfile reusing prior prompt/tools.
        assert new_profile is not original_profile
        assert new_profile.system_prompt == "system prompt"
        assert new_profile.llm_client is client
        # ctx is mutated in place to the new profile.
        assert ctx.profile is new_profile
        # tool_registry is rebuilt from profile.tools via the global tool registry;
        # "Bash" is a real registered tool, so it maps to its class.
        assert set(ctx.tool_registry) == {"Bash"}

        # Underlying fallback advanced the active candidate.
        assert client.active_candidate.provider == "openrouter"

        assert isinstance(event, events.FallbackModelConfigWarnEvent)
        assert event.from_provider == "openai"
        assert event.to_provider == "openrouter"
        assert event.from_model == "gpt-5.5"
        assert event.to_model == "gpt-5.4"
        assert event.sub_agent_type is None

        # A FallbackModelConfigWarnEntry was appended to history.
        entries = [it for it in session.conversation_history if isinstance(it, message.FallbackModelConfigWarnEntry)]
        assert len(entries) == 1
        assert entries[0].from_provider == "openai"
        assert entries[0].to_provider == "openrouter"

    asyncio.run(_test())


def test_fallback_model_uses_apply_llm_client_change_hook(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home

    async def _test() -> None:
        client = _fallback_client()
        executor, ctx, _session = _build_executor(tmp_path=tmp_path, llm_client=client)

        captured: list[LLMClientABC] = []

        def _apply(llm_client: LLMClientABC) -> AgentProfile:
            captured.append(llm_client)
            return AgentProfile(
                llm_client=llm_client,
                system_prompt=f"rebuilt {llm_client.model_name}",
                tools=[],
                attachments=[],
            )

        ctx.apply_llm_client_change = _apply
        result = executor._fallback_model("insufficient_quota")  # pyright: ignore[reportPrivateUsage]
        assert result is not None
        new_profile, _event = result
        # Hook is called with the (same) client object, AFTER it advanced candidates.
        assert captured == [client]
        assert new_profile.system_prompt == "rebuilt gpt-5.4"
        assert ctx.profile is new_profile

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# _fallback_compact_model
# ---------------------------------------------------------------------------


def test_fallback_compact_model_uses_explicit_compact_client_without_touching_main_profile(
    isolated_home: Path, tmp_path: Path
) -> None:
    del isolated_home

    async def _test() -> None:
        main_client = _StubClient(_config("openai", "main"))
        compact_client = _fallback_client()
        executor, ctx, session = _build_executor(
            tmp_path=tmp_path,
            llm_client=main_client,
            compact_llm_client=compact_client,
        )
        original_profile = ctx.profile
        result = executor._fallback_compact_model("insufficient_quota")  # pyright: ignore[reportPrivateUsage]
        assert result is not None
        new_profile, event = result

        # Explicit compact client path: main profile is returned UNCHANGED.
        assert new_profile is original_profile
        assert ctx.profile is original_profile
        # The compact client advanced its candidate.
        assert compact_client.active_candidate.provider == "openrouter"
        assert event.from_provider == "openai"
        assert event.to_provider == "openrouter"
        entries = [it for it in session.conversation_history if isinstance(it, message.FallbackModelConfigWarnEntry)]
        assert len(entries) == 1

    asyncio.run(_test())


def test_fallback_compact_model_falls_back_to_main_client_and_rebuilds_profile(
    isolated_home: Path, tmp_path: Path
) -> None:
    del isolated_home

    async def _test() -> None:
        # No explicit compact client -> compaction uses the main client; on fallback
        # the main profile IS rebuilt (mirrors _fallback_model behavior).
        client = _fallback_client()
        executor, ctx, _session = _build_executor(tmp_path=tmp_path, llm_client=client, compact_llm_client=None)
        original_profile = ctx.profile
        result = executor._fallback_compact_model("insufficient_quota")  # pyright: ignore[reportPrivateUsage]
        assert result is not None
        new_profile, event = result
        assert new_profile is not original_profile
        assert ctx.profile is new_profile
        assert new_profile.system_prompt == "system prompt"
        assert client.active_candidate.provider == "openrouter"
        assert event.to_provider == "openrouter"

    asyncio.run(_test())


def test_fallback_compact_model_returns_none_for_non_fallback_client(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    executor, ctx, session = _build_executor(
        tmp_path=tmp_path,
        llm_client=_StubClient(_config("openai", "main")),
        compact_llm_client=_StubClient(_config("openai", "compact")),
    )
    before = len(session.conversation_history)
    result = executor._fallback_compact_model("rate limit reached")  # pyright: ignore[reportPrivateUsage]
    assert result is None
    assert ctx.profile is ctx.profile
    assert len(session.conversation_history) == before


# ---------------------------------------------------------------------------
# is_fallbackable_llm_error markers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("insufficient_quota", True),
        ("You exceeded your current quota", True),
        ("billing issue", True),
        ("credit balance too low", True),
        ("model_not_found", True),
        ("permission_denied", True),
        ("usage_limit_reached", True),
        ("Does not have access to model gpt-x", True),
        # Overflow is explicitly excluded even though phrasing is error-like.
        ("prompt is too long", False),
        ("context length exceeded", False),
        # Generic transient errors are not fallbackable.
        ("rate limit reached", False),
        ("internal server error", False),
        ("", False),
    ],
)
def test_is_fallbackable_llm_error(text: str, expected: bool) -> None:
    assert is_fallbackable_llm_error(text) is expected
