from __future__ import annotations

from pathlib import Path

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, model, op


class ExportCommand(CommandABC):
    """Export the current session into a standalone HTML transcript."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.EXPORT

    @property
    def summary(self) -> str:
        return "Export current session to HTML"

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "output path"

    @property
    def is_interactive(self) -> bool:
        return False

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        output_path = self._normalize_output_path(user_input.text, agent)
        return CommandResult(
            operations=[
                op.ExportSessionOperation(
                    session_id=agent.session.id,
                    output_path=str(output_path) if output_path is not None else None,
                )
            ]
        )

    def _normalize_output_path(self, raw: str, agent: Agent) -> Path | None:
        trimmed = raw.strip()
        if trimmed:
            candidate = Path(trimmed).expanduser()
            if not candidate.is_absolute():
                candidate = Path(agent.session.work_dir) / candidate
            if candidate.suffix.lower() != ".html":
                candidate = candidate.with_suffix(".html")
            return candidate
        return None
