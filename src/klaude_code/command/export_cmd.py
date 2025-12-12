from __future__ import annotations

import subprocess
from pathlib import Path

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model
from klaude_code.session.export import build_export_html, get_default_export_path


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

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        try:
            output_path = self._resolve_output_path(raw, agent)
            html_doc = self._build_html(agent)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html_doc, encoding="utf-8")
            self._open_file(output_path)
            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content=f"Session exported and opened: {output_path}",
                    command_output=model.CommandOutput(command_name=self.name),
                ),
            )
            return CommandResult(events=[event])
        except Exception as exc:  # pragma: no cover - safeguard for unexpected errors
            import traceback

            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content=f"Failed to export session: {exc}\n{traceback.format_exc()}",
                    command_output=model.CommandOutput(command_name=self.name, is_error=True),
                ),
            )
            return CommandResult(events=[event])

    def _resolve_output_path(self, raw: str, agent: Agent) -> Path:
        trimmed = raw.strip()
        if trimmed:
            candidate = Path(trimmed).expanduser()
            if not candidate.is_absolute():
                candidate = Path(agent.session.work_dir) / candidate
            if candidate.suffix.lower() != ".html":
                candidate = candidate.with_suffix(".html")
            return candidate
        return get_default_export_path(agent.session)

    def _open_file(self, path: Path) -> None:
        try:
            subprocess.run(["open", str(path)], check=True)
        except FileNotFoundError as exc:  # pragma: no cover - depends on platform
            msg = "`open` command not found; please open the HTML manually."
            raise RuntimeError(msg) from exc
        except subprocess.CalledProcessError as exc:  # pragma: no cover - depends on platform
            msg = f"Failed to open HTML with `open`: {exc}"
            raise RuntimeError(msg) from exc

    def _build_html(self, agent: Agent) -> str:
        profile = agent.profile
        system_prompt = (profile.system_prompt if profile else "") or ""
        tools = profile.tools if profile else []
        model_name = profile.llm_client.model_name if profile else "unknown"
        return build_export_html(agent.session, system_prompt, tools, model_name)
