from __future__ import annotations

import argparse
import shlex
from typing import NoReturn

from klaude_code.protocol import events, message

from .command_abc import Agent, CommandABC, CommandResult, WebModeRequest
from .types import CommandName

_WEB_USAGE = """Usage: /web [--host HOST] [--port PORT] [--no-open] [--debug]

Switch the current TUI session to web server mode.

Options:
  --host HOST  Host to bind web server (default: 127.0.0.1)
  --port PORT  Port to bind web server (default: 8765)
  --no-open    Do not open browser automatically
  --debug      Enable debug logs for web server
"""

class _WebArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)

def _create_parser() -> _WebArgumentParser:
    parser = _WebArgumentParser(prog="/web", add_help=False)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser

class WebCommand(CommandABC):
    """Switch the current TUI process into web server mode."""

    @property
    def name(self) -> CommandName:
        return CommandName.WEB

    @property
    def summary(self) -> str:
        return "Switch to web mode"

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "options"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        try:
            args = shlex.split(user_input.text)
        except ValueError as exc:
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content=f"Invalid /web arguments: {exc}\n\n{_WEB_USAGE}",
                        is_error=True,
                    )
                ]
            )

        if any(arg in {"-h", "--help"} for arg in args):
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content=_WEB_USAGE,
                    )
                ]
            )

        try:
            parsed = _create_parser().parse_args(args)
        except ValueError as exc:
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content=f"Invalid /web arguments: {exc}\n\n{_WEB_USAGE}",
                        is_error=True,
                    )
                ]
            )

        return CommandResult(
            events=[
                events.NoticeEvent(
                    session_id=agent.session.id,
                    content="Switching to web mode...",
                )
            ],
            web_mode_request=WebModeRequest(
                host=parsed.host,
                port=parsed.port,
                no_open=parsed.no_open,
                debug=True if parsed.debug else None,
            ),
        )
