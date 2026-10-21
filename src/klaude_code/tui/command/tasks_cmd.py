from pydantic import ValidationError

from klaude_code.protocol import events, message, op
from klaude_code.protocol.background_task import TaskRequest
from klaude_code.tui.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.tui.command.types import CommandName

_USAGE = (
    "Usage: /tasks [list | output TASK_ID [OFFSET [LIMIT]] | wait TASK_ID [OFFSET [LIMIT [WAIT_MS]]] | stop TASK_ID]"
)


class TasksCommand(CommandABC):
    @property
    def name(self) -> CommandName:
        return CommandName.TASKS

    @property
    def summary(self) -> str:
        return "Browse tasks with live output; list, read, wait for, or stop Agent and Bash tasks"

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "list | output TASK_ID [OFFSET [LIMIT]] | wait TASK_ID [OFFSET [LIMIT [WAIT_MS]]] | stop TASK_ID"

    @property
    def runs_in_background(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        args = user_input.text.split()
        if not args:
            return CommandResult(open_task_panel=True)
        request: TaskRequest | None = None
        if args == ["list"]:
            request = TaskRequest(action="list")
        elif len(args) == 2 and args[0] == "stop":
            request = TaskRequest(action="stop", task_id=args[1])
        elif (2 <= len(args) <= 4 and args[0] == "output") or (2 <= len(args) <= 5 and args[0] == "wait"):
            try:
                params = dict(zip(("offset", "limit", "wait_ms"), (int(value) for value in args[2:]), strict=False))
            except ValueError:
                pass
            else:
                try:
                    request = TaskRequest.model_validate({"action": args[0], "task_id": args[1], **params})
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
        if request is None:
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content=_USAGE,
                        is_error=True,
                    )
                ]
            )
        return CommandResult(operations=[op.ManageTasksOperation(session_id=agent.session.id, request=request)])
