import typer

from klaude_code.app.auth_flow import execute_switch
from klaude_code.protocol import events, message

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


def _parse_switch_args(text: str) -> tuple[str, str | None]:
    args = text.split()
    if not args:
        return "codex", None
    if len(args) == 1:
        if args[0].lower() == "codex":
            return "codex", None
        return "codex", args[0]
    if len(args) == 2:
        return args[0], args[1]
    raise ValueError(f"Unexpected argument for switch: {args[2]}")


class SwitchCommand(CommandABC):
    """Switch active OAuth account."""

    @property
    def name(self) -> CommandName:
        return CommandName.SWITCH

    @property
    def summary(self) -> str:
        return "Switch active OAuth account"

    @property
    def is_interactive(self) -> bool:
        return True

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "[account|provider account]"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        try:
            provider, account_name = _parse_switch_args(user_input.text.strip())
        except ValueError as e:
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content=f"Switch failed: {e}",
                        is_error=True,
                    )
                ]
            )

        try:
            execute_switch(provider, account_name=account_name)
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
                            content=f"Switch failed (exit code: {e.exit_code}).",
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
                    content="Switch flow completed.",
                )
            ]
        )