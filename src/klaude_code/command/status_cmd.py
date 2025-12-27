from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model
from klaude_code.session.session import Session


class AggregatedUsage(model.BaseModel):
    """Aggregated usage statistics including per-model breakdown."""

    total: model.Usage
    by_model: list[model.TaskMetadata]
    task_count: int


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


def _format_tokens(tokens: int) -> str:
    """Format token count with K/M suffix for readability."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.2f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


def _format_cost(cost: float | None, currency: str = "USD") -> str:
    """Format cost with currency symbol."""
    if cost is None:
        return "-"
    symbol = "¥" if currency == "CNY" else "$"
    if cost < 0.01:
        return f"{symbol}{cost:.4f}"
    return f"{symbol}{cost:.2f}"


def _format_model_usage_line(meta: model.TaskMetadata) -> str:
    """Format a single model's usage as a line."""
    model_label = meta.model_name
    if meta.provider:
        model_label = f"{meta.model_name} ({meta.provider})"

    usage = meta.usage
    if not usage:
        return f"      {model_label}: no usage data"

    cost_str = _format_cost(usage.total_cost, usage.currency)
    return (
        f"      {model_label}: "
        f"{_format_tokens(usage.input_tokens)} input, "
        f"{_format_tokens(usage.output_tokens)} output, "
        f"{_format_tokens(usage.cached_tokens)} cache read, "
        f"{_format_tokens(usage.reasoning_tokens)} thinking, "
        f"({cost_str})"
    )


def format_status_content(aggregated: AggregatedUsage) -> str:
    """Format session status with per-model breakdown."""
    lines: list[str] = []

    # Total cost line
    total_cost_str = _format_cost(aggregated.total.total_cost, aggregated.total.currency)
    lines.append(f"Total cost: {total_cost_str}")

    # Per-model breakdown
    if aggregated.by_model:
        lines.append("Usage by model:")
        for stats in aggregated.by_model:
            lines.append(_format_model_usage_line(stats))

    return "\n".join(lines)


class StatusCommand(CommandABC):
    """Display session usage statistics."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.STATUS

    @property
    def summary(self) -> str:
        return "Show session usage statistics"

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        del user_input  # unused
        session = agent.session
        aggregated = accumulate_session_usage(session)

        event = events.DeveloperMessageEvent(
            session_id=session.id,
            item=model.DeveloperMessageItem(
                content=format_status_content(aggregated),
                command_output=model.CommandOutput(
                    command_name=self.name,
                    ui_extra=model.SessionStatusUIExtra(
                        usage=aggregated.total,
                        task_count=aggregated.task_count,
                        by_model=aggregated.by_model,
                    ),
                ),
            ),
        )

        return CommandResult(events=[event], persist_user_input=False, persist_events=False)
