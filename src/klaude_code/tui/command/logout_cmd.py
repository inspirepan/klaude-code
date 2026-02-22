import typer

from klaude_code.app.auth_flow import execute_logout
from klaude_code.protocol import commands, events, message

from .command_abc import Agent, CommandABC, CommandResult


class LogoutCommand(CommandABC):
    """Logout from OAuth providers."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.LOGOUT

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
        return "provider"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        provider = user_input.text.strip() or "codex"

        try:
            execute_logout(provider)
        except (KeyboardInterrupt, typer.Abort):
            return CommandResult(
                events=[
                    events.CommandOutputEvent(
                        session_id=agent.session.id,
                        command_name=self.name,
                        content="(cancelled)",
                    )
                ]
            )
        except typer.Exit as e:
            if e.exit_code not in (None, 0):
                return CommandResult(
                    events=[
                        events.CommandOutputEvent(
                            session_id=agent.session.id,
                            command_name=self.name,
                            content=f"Logout failed (exit code: {e.exit_code}).",
                            is_error=True,
                        )
                    ]
                )
            return CommandResult(
                events=[
                    events.CommandOutputEvent(
                        session_id=agent.session.id,
                        command_name=self.name,
                        content="(cancelled)",
                    )
                ]
            )

        return CommandResult(
            events=[
                events.CommandOutputEvent(
                    session_id=agent.session.id,
                    command_name=self.name,
                    content="Logout flow completed.",
                )
            ]
        )
