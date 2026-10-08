from pydantic import ValidationError

from klaude_code.protocol import events, message, op
from klaude_code.tui.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.tui.command.types import CommandName

_USAGE = "Usage: /tasks [list | output TASK_ID [OFFSET [LIMIT]] | stop TASK_ID]"


class TasksCommand(CommandABC):
    @property
    def name(self) -> CommandName:
        return CommandName.TASKS

    @property
    def summary(self) -> str:
        return "List background commands, view output, or stop a command"

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "list | output TASK_ID [OFFSET [LIMIT]] | stop TASK_ID"

    @property
    def runs_in_background(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        args = user_input.text.split()
        operation: op.ManageShellOperation | None = None
        if not args or args == ["list"]:
            operation = op.ManageShellOperation(session_id=agent.session.id, action="list")
        elif len(args) == 2 and args[0] == "stop":
            operation = op.ManageShellOperation(session_id=agent.session.id, action="stop", task_id=args[1])
        elif 2 <= len(args) <= 4 and args[0] == "output":
            try:
                params = dict(zip(("offset", "limit"), (int(value) for value in args[2:]), strict=False))
            except ValueError:
                pass
            else:
                try:
                    operation = op.ManageShellOperation.model_validate(
                        {"session_id": agent.session.id, "action": "output", "task_id": args[1], **params}
                    )
                except ValidationError as exc:
                    errors = "; ".join(
                        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                        for error in exc.errors(include_url=False, include_input=False)
                    )
                    return CommandResult(
                        events=[
                            events.NoticeEvent(
                                session_id=agent.session.id, content=f"{_USAGE}\n{errors}", is_error=True
                            )
                        ]
                    )
        if operation is None:
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content=_USAGE,
                        is_error=True,
                    )
                ]
            )
        return CommandResult(operations=[operation])
