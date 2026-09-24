import asyncio

from klaude_code.protocol import events, message

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class ReloadCommand(CommandABC):
    """Restart the server on the installed code once its sessions are idle."""

    @property
    def name(self) -> CommandName:
        return CommandName.RELOAD

    @property
    def summary(self) -> str:
        return "Restart the server on the latest installed code (waits for active sessions)"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused
        from klaude_code.tui.client.server_api import describe_reload_response, request_server_reload

        try:
            body = await asyncio.to_thread(request_server_reload)
        except Exception as exc:
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id, content=f"Server reload failed: {exc}", is_error=True
                    )
                ]
            )
        return CommandResult(
            events=[events.NoticeEvent(session_id=agent.session.id, content=describe_reload_response(body))]
        )
