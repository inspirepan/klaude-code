from pathlib import Path

import pytest

from klaude_code.agent.session_stats import (
    accumulate_session_usage,
    build_session_stats_ui_extra,
    collect_message_stats,
)
from klaude_code.protocol import message
from klaude_code.protocol.models import SessionStatsUIExtra, TaskMetadata, TaskMetadataItem, Usage
from klaude_code.session.session import Session


def test_usage_keeps_main_models_and_individual_child_runs_separate(tmp_path: Path) -> None:
    session = Session(work_dir=tmp_path)
    main = TaskMetadata(model_name="shared", provider="provider", usage=Usage(input_tokens=100, input_cost=1))
    first = TaskMetadata(
        model_name="shared",
        provider="provider",
        sub_agent_name="finder",
        description="scan tools",
        usage=Usage(input_tokens=20, input_cost=0.2),
    )
    second = first.model_copy(update={"description": "scan UI"})
    session.conversation_history.extend(
        [
            TaskMetadataItem(main_agent=main, sub_agent_task_metadata=[first]),
            TaskMetadataItem(main_agent=main),
            TaskMetadataItem(background_task_id="background-1", sub_agent_task_metadata=[second]),
        ]
    )

    stats = build_session_stats_ui_extra(session)

    assert stats.task_count == 2
    assert stats.usage.input_tokens == 240
    assert stats.usage.total_cost == pytest.approx(2.4)
    assert len(stats.by_model) == len(stats.main_agent_by_model) == 1
    assert stats.by_model[0].usage is not None
    assert stats.by_model[0].usage.input_tokens == 240
    assert stats.main_agent_by_model[0].usage is not None
    assert stats.main_agent_by_model[0].usage.input_tokens == 200
    assert stats.main_agent_by_model[0].usage.total_cost == 2
    assert stats.sub_agent_runs == [first, second]
    assert main.usage is not None and main.usage.input_tokens == 100


def test_same_model_and_provider_keep_currencies_separate(tmp_path: Path) -> None:
    session = Session(work_dir=tmp_path)
    session.conversation_history.extend(
        TaskMetadataItem(
            main_agent=TaskMetadata(
                model_name="shared",
                provider="provider",
                usage=Usage(input_tokens=100, input_cost=cost, currency=currency),
            )
        )
        for currency, cost in [("USD", 1), ("CNY", 2), ("USD", 3)]
    )

    aggregated = accumulate_session_usage(session)

    assert len(aggregated.by_model) == len(aggregated.main_agent_by_model) == 2
    assert {meta.usage.currency: meta.usage.total_cost for meta in aggregated.by_model if meta.usage} == {
        "USD": 4,
        "CNY": 2,
    }
    assert aggregated.total.input_tokens == 300
    assert aggregated.total.total_cost is None


def test_settled_background_run_without_metadata_remains_visible(tmp_path: Path) -> None:
    session = Session(work_dir=tmp_path)
    session.conversation_history.append(TaskMetadataItem(background_task_id="failed-or-lost-agent"))

    stats = build_session_stats_ui_extra(session)

    assert stats.task_count == 0
    assert len(stats.sub_agent_runs) == 1
    assert stats.sub_agent_runs[0].usage is None
    assert stats.main_agent_by_model == stats.by_model == []
    assert stats.usage.total_cost is None


def test_user_message_count_excludes_reports_and_peer_messages(tmp_path: Path) -> None:
    session = Session(work_dir=tmp_path)
    sources: list[message.UserMessageSource | None] = [
        None,
        "user",
        "bash_mode",
        "peer_message",
        "task_completion",
        "shell_completion",
    ]
    session.conversation_history.extend(message.UserMessage(parts=[], source=source) for source in sources)
    session.conversation_history.append(message.AssistantMessage(parts=[]))

    stats = collect_message_stats(session)

    assert stats.user_messages == 3
    assert stats.assistant_messages == 1
    assert stats.total_messages == 4


def test_empty_stats_and_legacy_event_defaults(tmp_path: Path) -> None:
    stats = build_session_stats_ui_extra(Session(work_dir=tmp_path))
    legacy = stats.model_dump(exclude={"main_agent_by_model", "sub_agent_runs"})

    restored = SessionStatsUIExtra.model_validate(legacy)

    assert restored.main_agent_by_model == restored.sub_agent_runs == restored.by_model == []
    assert restored.usage.total_cost is None
