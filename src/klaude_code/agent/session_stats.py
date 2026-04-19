from __future__ import annotations

from pydantic import BaseModel

from klaude_code.protocol import message
from klaude_code.protocol.models import SessionStatsUIExtra, TaskMetadata, TaskMetadataItem, Usage
from klaude_code.session.session import Session


class AggregatedUsage(BaseModel):
    """Aggregated usage statistics including per-model breakdown."""

    total: Usage
    by_model: list[TaskMetadata]
    task_count: int


class MessageStats(BaseModel):
    user_messages: int
    assistant_messages: int
    tool_calls: int
    tool_results: int

    @property
    def total_messages(self) -> int:
        return self.user_messages + self.assistant_messages + self.tool_results


def format_tokens(tokens: int) -> str:
    """Format token count with K/M suffix for readability."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.2f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


def format_cost(cost: float | None, currency: str = "USD") -> str:
    """Format cost with currency symbol."""
    if cost is None:
        return "-"
    symbol = "¥" if currency == "CNY" else "$"
    if cost < 0.01:
        return f"{symbol}{cost:.4f}"
    return f"{symbol}{cost:.2f}"


def accumulate_session_usage(session: Session) -> AggregatedUsage:
    """Accumulate usage statistics from all TaskMetadataItems in session history."""
    all_metadata: list[TaskMetadata] = []
    task_count = 0

    for item in session.conversation_history:
        if isinstance(item, TaskMetadataItem):
            task_count += 1
            all_metadata.append(item.main_agent)
            all_metadata.extend(item.sub_agent_task_metadata)

    by_model = TaskMetadata.aggregate_by_model(all_metadata)

    total = Usage()
    for meta in by_model:
        if not meta.usage:
            continue
        usage = meta.usage

        if total.currency == "USD" and usage.currency:
            total.currency = usage.currency

        total.input_tokens += usage.input_tokens
        total.cached_tokens += usage.cached_tokens
        total.reasoning_tokens += usage.reasoning_tokens
        total.output_tokens += usage.output_tokens

        if usage.input_cost is not None:
            total.input_cost = (total.input_cost or 0.0) + usage.input_cost
        if usage.output_cost is not None:
            total.output_cost = (total.output_cost or 0.0) + usage.output_cost
        if usage.cache_read_cost is not None:
            total.cache_read_cost = (total.cache_read_cost or 0.0) + usage.cache_read_cost

        if usage.context_size is not None:
            total.context_size = usage.context_size
        if usage.context_limit is not None:
            total.context_limit = usage.context_limit

    return AggregatedUsage(total=total, by_model=by_model, task_count=task_count)


def collect_message_stats(session: Session) -> MessageStats:
    user_messages = 0
    assistant_messages = 0
    tool_calls = 0
    tool_results = 0

    for item in session.conversation_history:
        if isinstance(item, message.UserMessage):
            user_messages += 1
            continue
        if isinstance(item, message.AssistantMessage):
            assistant_messages += 1
            tool_calls += sum(1 for part in item.parts if isinstance(part, message.ToolCallPart))
            continue
        if isinstance(item, message.ToolResultMessage):
            tool_results += 1

    return MessageStats(
        user_messages=user_messages,
        assistant_messages=assistant_messages,
        tool_calls=tool_calls,
        tool_results=tool_results,
    )


def build_session_stats_ui_extra(session: Session) -> SessionStatsUIExtra:
    aggregated = accumulate_session_usage(session)
    message_stats = collect_message_stats(session)
    events_file_path = str(Session.paths(session.work_dir).events_file(session.id))
    return SessionStatsUIExtra(
        events_file_path=events_file_path,
        session_id=session.id,
        user_messages_count=message_stats.user_messages,
        assistant_messages_count=message_stats.assistant_messages,
        tool_calls_count=message_stats.tool_calls,
        tool_results_count=message_stats.tool_results,
        total_messages_count=message_stats.total_messages,
        usage=aggregated.total,
        task_count=aggregated.task_count,
        by_model=aggregated.by_model,
    )
