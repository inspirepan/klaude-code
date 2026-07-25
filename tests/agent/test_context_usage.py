from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from klaude_code.agent import context_usage as context_usage_module
from klaude_code.agent.context_usage import analyze_context_usage
from klaude_code.agent.token_estimate import estimate_text_tokens
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import (
    ContextCategoryKey,
    ContextUsageUIExtra,
    DeveloperUIExtra,
    MemoryFileLoaded,
    MemoryLoadedUIItem,
    SkillListingUIItem,
    Usage,
)
from klaude_code.session import Session


def _llm_config(*, context_limit: int = 200_000, max_tokens: int = 32_000) -> llm_param.LLMConfigParameter:
    return llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.ANTHROPIC,
        model_id="test-model",
        context_limit=context_limit,
        max_tokens=max_tokens,
    )


def _tool(name: str, description: str) -> llm_param.ToolSchema:
    return llm_param.ToolSchema(
        name=name,
        type="function",
        description=description,
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
    )


@pytest.fixture(autouse=True)
def _no_pending_attachments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real filesystem's memory and skills out of these token assertions.

    Tests that care about the pending-attachment preview patch these back explicitly.
    """

    async def _none(_session: Session) -> None:
        return None

    monkeypatch.setattr(context_usage_module, "memory_attachment", _none)
    monkeypatch.setattr(context_usage_module, "available_skills_attachment", _none)


def _run(**kwargs: Any) -> ContextUsageUIExtra:
    return asyncio.run(analyze_context_usage(**kwargs))


def _analyze(
    session: Session,
    *,
    system_prompt: str = "",
    tools: list[llm_param.ToolSchema] | None = None,
) -> dict[ContextCategoryKey, int]:
    usage = _run(
        session=session,
        system_prompt=system_prompt,
        tools=tools or [],
        llm_config=_llm_config(),
        model_name="test-model",
    )
    return {category.key: category.tokens for category in usage.categories}


def test_cjk_text_is_not_underestimated_like_chars_over_four() -> None:
    chinese = "这是一段中文文本用来测试估算准确度"

    estimated = estimate_text_tokens(chinese)

    # A flat chars/4 would claim ~4 tokens for 17 CJK characters; real cost is near one each.
    assert estimated > len(chinese) // 4 * 2
    assert estimated <= len(chinese)


def test_english_prose_stays_close_to_chars_over_four() -> None:
    prose = "the quick brown fox jumps over the lazy dog and keeps running for a while"

    estimated = estimate_text_tokens(prose)

    assert abs(estimated - len(prose) // 4) <= len(prose) // 12


def test_empty_text_costs_nothing() -> None:
    assert estimate_text_tokens("") == 0


def test_memory_and_skill_blocks_are_split_out_of_messages() -> None:
    session = Session(work_dir=Path("."))
    session.conversation_history.append(
        message.DeveloperMessage(
            parts=message.text_parts_from_str("memory body " * 100),
            ui_extra=DeveloperUIExtra(items=[MemoryLoadedUIItem(files=[MemoryFileLoaded(path="AGENTS.md")])]),
        )
    )
    session.conversation_history.append(
        message.DeveloperMessage(
            parts=message.text_parts_from_str("skill metadata " * 100),
            ui_extra=DeveloperUIExtra(items=[SkillListingUIItem(names=["commit", "publish"])]),
        )
    )
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str("hello there")))

    tokens = _analyze(session)

    assert tokens["memory"] > 0
    assert tokens["skills"] > 0
    # The user message is the only thing left in "messages"; the two blocks above must not
    # be counted there as well.
    assert 0 < tokens["messages"] < min(tokens["memory"], tokens["skills"])


def test_skill_listing_cost_is_split_across_its_skills() -> None:
    session = Session(work_dir=Path("."))
    session.conversation_history.append(
        message.DeveloperMessage(
            parts=message.text_parts_from_str("skill metadata " * 100),
            ui_extra=DeveloperUIExtra(items=[SkillListingUIItem(names=["commit", "publish", "submit-pr"])]),
        )
    )

    usage = _run(
        session=session,
        system_prompt="",
        tools=[],
        llm_config=_llm_config(),
        model_name="test-model",
    )

    skills = next(section for section in usage.details if section.key == "skills")
    assert [entry.name for entry in skills.entries] == ["commit", "publish", "submit-pr"]
    skills_total = next(c.tokens for c in usage.categories if c.key == "skills")
    assert sum(entry.tokens for entry in skills.entries) == skills_total


def test_system_prompt_and_tools_are_counted() -> None:
    session = Session(work_dir=Path("."))

    tokens = _analyze(
        session,
        system_prompt="You are a helpful agent. " * 50,
        tools=[_tool("Read", "Reads a file " * 20), _tool("Write", "Writes a file " * 20)],
    )

    assert tokens["system_prompt"] > 0
    assert tokens["system_tools"] > 0


def test_categories_fit_inside_the_context_limit() -> None:
    session = Session(work_dir=Path("."))
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str("hi")))

    usage = _run(
        session=session,
        system_prompt="prompt",
        tools=[],
        llm_config=_llm_config(),
        model_name="test-model",
    )

    assert sum(category.tokens for category in usage.categories) == usage.context_limit


def test_real_api_usage_calibrates_the_estimates() -> None:
    session = Session(work_dir=Path("."))
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str("question " * 50)))
    session.conversation_history.append(
        message.AssistantMessage(
            parts=message.text_parts_from_str("answer " * 50),
            usage=Usage(input_tokens=90_000, output_tokens=100, context_size=90_000),
            stop_reason="stop",
        )
    )

    usage = _run(
        session=session,
        system_prompt="prompt",
        tools=[],
        llm_config=_llm_config(),
        model_name="test-model",
    )

    assert usage.is_calibrated
    # Scaled to the reported context size rather than the much smaller raw estimate.
    assert usage.used_tokens == 90_000


def test_aborted_response_usage_is_not_used_for_calibration() -> None:
    session = Session(work_dir=Path("."))
    session.conversation_history.append(
        message.AssistantMessage(
            parts=message.text_parts_from_str("partial"),
            usage=Usage(input_tokens=90_000, output_tokens=0, context_size=90_000),
            stop_reason="aborted",
        )
    )

    usage = _run(
        session=session,
        system_prompt="prompt",
        tools=[],
        llm_config=_llm_config(),
        model_name="test-model",
    )

    assert not usage.is_calibrated
    assert usage.used_tokens < 1_000


def test_missing_context_limit_reports_usage_without_free_space() -> None:
    session = Session(work_dir=Path("."))
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str("hi")))

    usage = _run(
        session=session,
        system_prompt="prompt",
        tools=[],
        llm_config=llm_param.LLMConfigParameter(protocol=llm_param.LLMClientProtocol.ANTHROPIC, model_id="m"),
        model_name="m",
    )

    assert usage.context_limit == 0
    assert usage.usage_percent == 0.0
    assert not any(category.key == "free" for category in usage.categories)
    assert usage.used_tokens > 0


def test_pending_memory_is_reported_before_the_first_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh session should show the memory it is about to send, not zero."""
    session = Session(work_dir=Path("."))

    async def _pending_memory(_session: Session) -> message.DeveloperMessage:
        return message.DeveloperMessage(
            parts=message.text_parts_from_str("memory body " * 200),
            ui_extra=DeveloperUIExtra(items=[MemoryLoadedUIItem(files=[MemoryFileLoaded(path="AGENTS.md")])]),
        )

    monkeypatch.setattr(context_usage_module, "memory_attachment", _pending_memory)

    usage = _run(
        session=session,
        system_prompt="prompt",
        tools=[],
        llm_config=_llm_config(),
        model_name="test-model",
    )

    memory = next(category for category in usage.categories if category.key == "memory")
    assert memory.tokens > 0
    section = next(section for section in usage.details if section.key == "memory")
    assert [entry.name for entry in section.entries] == ["AGENTS.md"]


def test_preview_does_not_mark_attachments_loaded_on_the_live_session() -> None:
    """The preview must not consume the session's not-yet-loaded state.

    If it did, the next real request would skip the memory and skill blocks entirely.
    """
    session = Session(work_dir=Path("."))
    tracker_before = dict(session.file_tracker)
    history_before = len(session.conversation_history)

    _run(
        session=session,
        system_prompt="prompt",
        tools=[],
        llm_config=_llm_config(),
        model_name="test-model",
    )

    assert session.file_tracker == tracker_before
    assert len(session.conversation_history) == history_before


def test_preview_failure_does_not_break_reporting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(_session: Session) -> message.DeveloperMessage:
        raise RuntimeError("skill discovery exploded")

    monkeypatch.setattr(context_usage_module, "available_skills_attachment", _boom)
    session = Session(work_dir=Path("."))
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str("hi")))

    usage = _run(
        session=session,
        system_prompt="prompt",
        tools=[],
        llm_config=_llm_config(),
        model_name="test-model",
    )

    assert usage.used_tokens > 0
    assert next(category for category in usage.categories if category.key == "skills").tokens == 0


def test_memory_files_are_attributed_by_their_own_size() -> None:
    """A big memory file must not be reported at the same cost as a tiny one."""
    session = Session(work_dir=Path("."))
    big = "Contents of /big.md (project instructions):\n\n" + "long body " * 400
    small = "Contents of /small.md (user instructions):\n\n" + "tiny "
    session.conversation_history.append(
        message.DeveloperMessage(
            parts=message.text_parts_from_str(f"<system-reminder>\n{big}\n\n{small}\n</system-reminder>"),
            ui_extra=DeveloperUIExtra(
                items=[MemoryLoadedUIItem(files=[MemoryFileLoaded(path="/big.md"), MemoryFileLoaded(path="/small.md")])]
            ),
        )
    )

    usage = _run(
        session=session,
        system_prompt="",
        tools=[],
        llm_config=_llm_config(),
        model_name="test-model",
    )

    section = next(section for section in usage.details if section.key == "memory")
    by_name = {entry.name: entry.tokens for entry in section.entries}
    assert by_name["/big.md"] > by_name["/small.md"] * 20
    # Entries must still add up to the category total.
    memory_total = next(c.tokens for c in usage.categories if c.key == "memory")
    assert sum(by_name.values()) == memory_total


def test_skills_are_attributed_by_their_listing_line() -> None:
    """Weighting reads the one-line-per-skill listing format from the skill loader."""
    session = Session(work_dir=Path("."))
    listing = "\n".join(
        [
            "<available_skills>",
            f'  <skill name="verbose" path="/a/SKILL.md">{"a long description " * 40}</skill>',
            '  <skill name="terse" path="/b/SKILL.md">short</skill>',
            "</available_skills>",
        ]
    )
    session.conversation_history.append(
        message.DeveloperMessage(
            parts=message.text_parts_from_str(listing),
            ui_extra=DeveloperUIExtra(items=[SkillListingUIItem(names=["verbose", "terse"])]),
        )
    )

    usage = _run(
        session=session,
        system_prompt="",
        tools=[],
        llm_config=_llm_config(),
        model_name="test-model",
    )

    by_name = {
        entry.name: entry.tokens for section in usage.details if section.key == "skills" for entry in section.entries
    }
    assert by_name["verbose"] > by_name["terse"] * 10


def test_entries_fall_back_to_an_even_split_when_unlocatable() -> None:
    session = Session(work_dir=Path("."))
    session.conversation_history.append(
        message.DeveloperMessage(
            parts=message.text_parts_from_str("opaque block with no per-item markers " * 20),
            ui_extra=DeveloperUIExtra(
                items=[MemoryLoadedUIItem(files=[MemoryFileLoaded(path="/x.md"), MemoryFileLoaded(path="/y.md")])]
            ),
        )
    )

    usage = _run(
        session=session,
        system_prompt="",
        tools=[],
        llm_config=_llm_config(),
        model_name="test-model",
    )

    section = next(section for section in usage.details if section.key == "memory")
    tokens = sorted(entry.tokens for entry in section.entries)
    assert tokens[0] > 0
    assert tokens[1] - tokens[0] <= 1
