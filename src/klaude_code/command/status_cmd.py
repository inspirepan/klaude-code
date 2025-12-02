from klaude_code.command.command_abc import CommandABC, CommandResult
from klaude_code.command.registry import register_command
from klaude_code.core.agent import Agent
from klaude_code.protocol import commands, events, model
from klaude_code.session.session import Session


class AggregatedUsage(model.BaseModel):
    """Aggregated usage statistics including per-model breakdown."""

    total: model.Usage
    by_model: list[model.ModelUsageStats]
    task_count: int


def _accumulate_task_metadata(
    metadata: model.TaskMetadata,
    total: model.Usage,
    by_model: dict[tuple[str, str | None], model.ModelUsageStats],
    first_currency_set: list[bool],
) -> None:
    """Accumulate a single TaskMetadata into total and by_model stats."""
    if not metadata.usage:
        return

    usage = metadata.usage
    model_key = (metadata.model_name, metadata.provider)

    # Set currency from first usage item
    if not first_currency_set[0] and usage.currency:
        total.currency = usage.currency
        first_currency_set[0] = True

    # Accumulate to total
    total.input_tokens += usage.input_tokens
    total.cached_tokens += usage.cached_tokens
    total.reasoning_tokens += usage.reasoning_tokens
    total.output_tokens += usage.output_tokens
    total.total_tokens += usage.total_tokens

    if usage.input_cost is not None:
        total.input_cost = (total.input_cost or 0.0) + usage.input_cost
    if usage.output_cost is not None:
        total.output_cost = (total.output_cost or 0.0) + usage.output_cost
    if usage.cache_read_cost is not None:
        total.cache_read_cost = (total.cache_read_cost or 0.0) + usage.cache_read_cost
    if usage.total_cost is not None:
        total.total_cost = (total.total_cost or 0.0) + usage.total_cost

    if usage.context_usage_percent is not None:
        total.context_usage_percent = usage.context_usage_percent

    # Accumulate to per-model stats
    if model_key not in by_model:
        by_model[model_key] = model.ModelUsageStats(
            model_name=metadata.model_name,
            provider=metadata.provider,
            currency=usage.currency,
        )

    stats = by_model[model_key]
    stats.input_tokens += usage.input_tokens
    stats.output_tokens += usage.output_tokens
    stats.cached_tokens += usage.cached_tokens
    stats.reasoning_tokens += usage.reasoning_tokens
    # cache_write_tokens not tracked in Usage model currently
    if usage.total_cost is not None:
        stats.total_cost = (stats.total_cost or 0.0) + usage.total_cost


def accumulate_session_usage(session: Session) -> AggregatedUsage:
    """Accumulate usage statistics from all TaskMetadataItems in session history.

    Includes both main agent and sub-agent task metadata, grouped by model+provider.
    """
    total = model.Usage()
    by_model: dict[tuple[str, str | None], model.ModelUsageStats] = {}
    task_count = 0
    first_currency_set = [False]  # Use list for mutability in helper

    for item in session.conversation_history:
        if isinstance(item, model.TaskMetadataItem):
            task_count += 1

            # Accumulate main agent usage
            _accumulate_task_metadata(item.main, total, by_model, first_currency_set)

            # Accumulate sub-agent usages
            for sub_metadata in item.sub_agent_task_metadata:
                _accumulate_task_metadata(sub_metadata, total, by_model, first_currency_set)

    # Sort by_model by total_cost descending
    sorted_models = sorted(by_model.values(), key=lambda s: s.total_cost or 0.0, reverse=True)

    return AggregatedUsage(total=total, by_model=sorted_models, task_count=task_count)


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


def _format_model_usage_line(stats: model.ModelUsageStats) -> str:
    """Format a single model's usage as a line."""
    model_label = stats.model_name
    if stats.provider:
        model_label = f"{stats.model_name} ({stats.provider})"

    cost_str = _format_cost(stats.total_cost, stats.currency)
    return (
        f"      {model_label}: "
        f"{_format_tokens(stats.input_tokens)} input, "
        f"{_format_tokens(stats.output_tokens)} output, "
        f"{_format_tokens(stats.cached_tokens)} cache read, "
        f"{_format_tokens(stats.reasoning_tokens)} thinking, "
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


@register_command
class StatusCommand(CommandABC):
    """Display session usage statistics."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.STATUS

    @property
    def summary(self) -> str:
        return "Show session usage statistics"

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        session = agent.session
        aggregated = accumulate_session_usage(session)

        event = events.DeveloperMessageEvent(
            session_id=session.id,
            item=model.DeveloperMessageItem(
                content=format_status_content(aggregated),
                command_output=model.CommandOutput(
                    command_name=self.name,
                    ui_extra=model.ToolResultUIExtra(
                        type=model.ToolResultUIExtraType.SESSION_STATUS,
                        session_status=model.SessionStatusUIExtra(
                            usage=aggregated.total,
                            task_count=aggregated.task_count,
                            by_model=aggregated.by_model,
                        ),
                    ),
                ),
            ),
        )

        return CommandResult(events=[event])
