from klaude_code.protocol import commands, events, message, model
from klaude_code.session.session import Session

from .command_abc import Agent, CommandABC, CommandResult


class AggregatedUsage(model.BaseModel):
    """Aggregated usage statistics including per-model breakdown."""

    total: model.Usage
    by_model: list[model.TaskMetadata]
    task_count: int


class MessageStats(model.BaseModel):
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
    """Accumulate usage statistics from all TaskMetadataItems in session history.

    Includes both main agent and sub-agent task metadata, grouped by model+provider.
    """
    all_metadata: list[model.TaskMetadata] = []
    task_count = 0

    for item in session.conversation_history:
        if isinstance(item, model.TaskMetadataItem):
            task_count += 1
            all_metadata.append(item.main_agent)
            all_metadata.extend(item.sub_agent_task_metadata)

    # Aggregate by model+provider
    by_model = model.TaskMetadata.aggregate_by_model(all_metadata)

    # Calculate total from aggregated results
    total = model.Usage()
    for meta in by_model:
        if not meta.usage:
            continue
        usage = meta.usage

        # Set currency from first
        if total.currency == "USD" and usage.currency:
            total.currency = usage.currency

        # Accumulate primary token fields (total_tokens is computed)
        total.input_tokens += usage.input_tokens
        total.cached_tokens += usage.cached_tokens
        total.reasoning_tokens += usage.reasoning_tokens
        total.output_tokens += usage.output_tokens

        # Accumulate cost components (total_cost is computed)
        if usage.input_cost is not None:
            total.input_cost = (total.input_cost or 0.0) + usage.input_cost
        if usage.output_cost is not None:
            total.output_cost = (total.output_cost or 0.0) + usage.output_cost
        if usage.cache_read_cost is not None:
            total.cache_read_cost = (total.cache_read_cost or 0.0) + usage.cache_read_cost

        # Track peak context window size (max across all tasks)
        if usage.context_size is not None:
            total.context_size = usage.context_size

        # Keep the latest context_limit for computed context_usage_percent
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


class StatusCommand(CommandABC):
    """Display session usage statistics."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.STATUS

    @property
    def summary(self) -> str:
        return "Show session usage statistics"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused
        session = agent.session
        aggregated = accumulate_session_usage(session)
        message_stats = collect_message_stats(session)
        events_file_path = str(Session.paths().events_file(session.id))

        event = events.CommandOutputEvent(
            session_id=session.id,
            command_name=self.name,
            ui_extra=model.SessionStatusUIExtra(
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
            ),
        )

        return CommandResult(events=[event])
