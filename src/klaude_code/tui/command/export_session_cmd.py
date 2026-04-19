from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

from klaude_code.protocol import events, message

from .command_abc import Agent, CommandABC, CommandResult
from .export_session_html import render_session_export_html
from .types import CommandName

_EXPORT_SESSION_USAGE = """Usage: /export-session [OUTPUT.html]

Export the current session to a standalone HTML file.

Arguments:
  OUTPUT.html  Optional output path. Relative paths resolve from the session work dir.
               If omitted, writes `klaude-session-<session>.html` in the work dir.
"""

class _ExportSessionArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)

def _create_parser() -> _ExportSessionArgumentParser:
    parser = _ExportSessionArgumentParser(prog="/export-session", add_help=False)
    parser.add_argument("output", nargs="?")
    return parser

class ExportSessionCommand(CommandABC):
    @property
    def name(self) -> CommandName:
        return CommandName.EXPORT_SESSION

    @property
    def summary(self) -> str:
        return "Export current session to HTML"

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "output.html"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        try:
            args = shlex.split(user_input.text)
        except ValueError as exc:
            return _command_output(
                agent, f"Invalid /export-session arguments: {exc}\n\n{_EXPORT_SESSION_USAGE}", is_error=True
            )

        if any(arg in {"-h", "--help"} for arg in args):
            return _command_output(agent, _EXPORT_SESSION_USAGE)

        try:
            parsed = _create_parser().parse_args(args)
        except ValueError as exc:
            return _command_output(
                agent, f"Invalid /export-session arguments: {exc}\n\n{_EXPORT_SESSION_USAGE}", is_error=True
            )

        if not agent.session.conversation_history:
            return _command_output(agent, "Nothing to export yet - start a conversation first.", is_error=True)

        output_path = _resolve_output_path(agent.session.work_dir, agent.session.id, agent.session.title, parsed.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        profile = agent.profile
        html_text = render_session_export_html(
            agent.session,
            system_prompt=profile.system_prompt if profile is not None else None,
            tools=profile.tools if profile is not None else None,
        )
        output_path.write_text(html_text, encoding="utf-8")
        opened = _open_exported_html(output_path)
        content = f"Exported session HTML to {output_path}"
        if opened:
            content += "\nOpened in the default app."
        return _command_output(agent, content)

def _resolve_output_path(work_dir: Path, session_id: str, title: str | None, raw_output: str | None) -> Path:
    if raw_output:
        output_path = Path(raw_output).expanduser()
        if not output_path.is_absolute():
            output_path = work_dir / output_path
        if output_path.exists() and output_path.is_dir():
            output_path = output_path / _default_file_name(session_id, title)
        elif output_path.suffix == "":
            output_path = output_path.with_suffix(".html")
        return output_path.resolve()
    return (work_dir / _default_file_name(session_id, title)).resolve()

def _default_file_name(session_id: str, title: str | None) -> str:
    title_slug = _slugify(title or "")
    if title_slug:
        return f"klaude-session-{title_slug}-{session_id[:8]}.html"
    return f"klaude-session-{session_id[:8]}.html"

def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return slug[:40].strip("-")

def _open_exported_html(output_path: Path) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run(["open", str(output_path)], check=False)
    except OSError:
        return False
    return True

def _command_output(agent: Agent, content: str, *, is_error: bool = False) -> CommandResult:
    return CommandResult(
        events=[
            events.NoticeEvent(
                session_id=agent.session.id,
                content=content,
                is_error=is_error,
            )
        ]
    )
