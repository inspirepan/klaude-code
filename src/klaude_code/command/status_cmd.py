from klaude_code.command.command_abc import CommandABC, CommandResult
from klaude_code.command.registry import register_command
from klaude_code.core.agent import Agent
from klaude_code.protocol import commands, events, model
from klaude_code.session.session import Session


def accumulate_session_usage(session: Session) -> tuple[model.Usage, int]:
    """Accumulate usage statistics from all ResponseMetadataItems in session history.

    Returns:
        A tuple of (accumulated_usage, task_count)
    """
    total = model.Usage()
    task_count = 0
    first_currency_set = False

    for item in session.conversation_history:
        if isinstance(item, model.ResponseMetadataItem) and item.usage:
            task_count += 1
            usage = item.usage

            # Set currency from first usage item
            if not first_currency_set and usage.currency:
                total.currency = usage.currency
                first_currency_set = True

            total.input_tokens += usage.input_tokens
            total.cached_tokens += usage.cached_tokens
            total.reasoning_tokens += usage.reasoning_tokens
            total.output_tokens += usage.output_tokens
            total.total_tokens += usage.total_tokens

            # Accumulate costs
            if usage.input_cost is not None:
                total.input_cost = (total.input_cost or 0.0) + usage.input_cost
            if usage.output_cost is not None:
                total.output_cost = (total.output_cost or 0.0) + usage.output_cost
            if usage.cache_read_cost is not None:
                total.cache_read_cost = (total.cache_read_cost or 0.0) + usage.cache_read_cost
            if usage.total_cost is not None:
                total.total_cost = (total.total_cost or 0.0) + usage.total_cost

            # Keep the latest context_usage_percent
            if usage.context_usage_percent is not None:
                total.context_usage_percent = usage.context_usage_percent

    return total, task_count


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


def format_status_content(usage: model.Usage) -> str:
    """Format session status as comma-separated text."""
    parts: list[str] = []

    parts.append(f"Input: {_format_tokens(usage.input_tokens)}")
    if usage.cached_tokens > 0:
        parts.append(f"Cached: {_format_tokens(usage.cached_tokens)}")
    parts.append(f"Output: {_format_tokens(usage.output_tokens)}")
    parts.append(f"Total: {_format_tokens(usage.total_tokens)}")

    if usage.total_cost is not None:
        parts.append(f"Cost: {_format_cost(usage.total_cost, usage.currency)}")

    return ", ".join(parts)


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
        usage, task_count = accumulate_session_usage(session)

        event = events.DeveloperMessageEvent(
            session_id=session.id,
            item=model.DeveloperMessageItem(
                content=format_status_content(usage),
                command_output=model.CommandOutput(
                    command_name=self.name,
                    ui_extra=model.ToolResultUIExtra(
                        type=model.ToolResultUIExtraType.SESSION_STATUS,
                        session_status=model.SessionStatusUIExtra(
                            usage=usage,
                            task_count=task_count,
                        ),
                    ),
                ),
            ),
        )

        return CommandResult(events=[event])
