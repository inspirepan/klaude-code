import asyncio
import shlex

import typer

from klaude_code.app.auth_flow import execute_logout
from klaude_code.protocol import events, message

from .auth_selector import select_provider
from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


def _parse_logout_args(text: str) -> tuple[str | None, str | None, bool]:
    args = shlex.split(text)
    if not args:
        return None, None, False

    provider = args[0]
    if provider.lower() != "codex":
        if len(args) > 1:
            raise ValueError(f"Unexpected argument for provider '{provider}': {args[1]}")
        return provider, None, False

    account_name: str | None = None
    all_accounts = False
    for arg in args[1:]:
        if arg == "--all":
            all_accounts = True
            continue
        if account_name is not None:
            raise ValueError(f"Unexpected argument for Codex logout: {arg}")
        account_name = arg

    if all_accounts and account_name is not None:
        raise ValueError("--all cannot be combined with an account name")

    return provider, account_name, all_accounts


class LogoutCommand(CommandABC):
    """Logout from OAuth providers."""

    @property
    def name(self) -> CommandName:
        return CommandName.LOGOUT

    @property
    def summary(self) -> str:
        return "Logout from provider"

    @property
    def is_interactive(self) -> bool:
        return True

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "provider [account|--all]"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        try:
            provider, account_name, all_accounts = _parse_logout_args(user_input.text.strip())
        except ValueError as e:
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content=f"Logout failed: {e}",
                        is_error=True,
                    )
                ]
            )

        if provider is None:
            try:
                provider = await asyncio.to_thread(
                    select_provider,
                    include_api_keys=True,
                    configured_only=True,
                    prompt="Select provider to logout:",
                )
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
            if account_name is not None or all_accounts:
                execute_logout(provider, account_name=account_name, all_accounts=all_accounts)
            else:
                execute_logout(provider)
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
                            content=f"Logout failed (exit code: {e.exit_code}).",
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
                    content="Logout flow completed.",
                )
            ]
        )
