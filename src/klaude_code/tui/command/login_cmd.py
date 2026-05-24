import asyncio
import shlex

import typer

from klaude_code.app.auth_flow import execute_login
from klaude_code.protocol import events, message

from .auth_selector import select_provider
from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


def _parse_login_args(text: str) -> tuple[str | None, str | None]:
    args = shlex.split(text)
    if not args:
        return None, None

    provider = args[0]
    if provider.lower() != "codex":
        if len(args) > 1:
            raise ValueError(f"Unexpected argument for provider '{provider}': {args[1]}")
        return provider, None

    account_name: str | None = None
    index = 1
    while index < len(args):
        arg = args[index]
        if arg in {"--name", "-n"}:
            if index + 1 >= len(args):
                raise ValueError(f"{arg} requires an account name")
            account_name = args[index + 1]
            index += 2
            continue
        if account_name is not None:
            raise ValueError(f"Unexpected argument for Codex login: {arg}")
        account_name = arg
        index += 1

    return provider, account_name


class LoginCommand(CommandABC):
    """Login to OAuth providers or configure API keys."""

    @property
    def name(self) -> CommandName:
        return CommandName.LOGIN

    @property
    def summary(self) -> str:
        return "Login to provider or configure API key"

    @property
    def is_interactive(self) -> bool:
        return True

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "provider [account|--name account]"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        try:
            provider, account_name = _parse_login_args(user_input.text.strip())
        except ValueError as e:
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content=f"Login failed: {e}",
                        is_error=True,
                    )
                ]
            )

        if provider is None:
            try:
                provider = await asyncio.to_thread(select_provider)
            except KeyboardInterrupt:
                provider = None
            if provider is None:
                return CommandResult(
                    events=[
                        events.NoticeEvent(
                            session_id=agent.session.id,
                            content="(cancelled)",
                        )
                    ]
                )

        try:
            if account_name is not None:
                execute_login(provider, account_name=account_name)
            else:
                execute_login(provider)
        except (KeyboardInterrupt, typer.Abort):
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content="(cancelled)",
                    )
                ]
            )
        except typer.Exit as e:
            if e.exit_code not in (None, 0):
                return CommandResult(
                    events=[
                        events.NoticeEvent(
                            session_id=agent.session.id,
                            content=f"Login failed (exit code: {e.exit_code}).",
                            is_error=True,
                        )
                    ]
                )
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content="(cancelled)",
                    )
                ]
            )

        return CommandResult(
            events=[
                events.NoticeEvent(
                    session_id=agent.session.id,
                    content="Login flow completed.",
                )
            ]
        )
