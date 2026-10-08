from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from klaude_code.protocol import llm_param, message, tools
from klaude_code.protocol.models import ShellTaskUIExtra
from klaude_code.protocol.shell_task import ShellTaskSnapshot
from klaude_code.tool.core.abc import ToolABC, load_desc
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.registry import register


def _format_task(task: ShellTaskSnapshot) -> str:
    status = task.status
    if task.exit_code is not None:
        status += f", exit {task.exit_code}"
    description = " ".join(task.description.split()) or " ".join(task.command.split())
    text = f"Task {task.task_id} [{status}]: {description}"
    if task.reason:
        text += f"; {' '.join(task.reason.split())}"
    if task.status == "lost":
        text += "; process state unknown, not a successful completion"
    if task.output_expired:
        text += "; output expired"
    return text


@register(tools.MANAGE_SHELL)
class ManageShellTool(ToolABC):
    class Arguments(BaseModel):
        action: Literal["list", "output", "wait", "stop"]
        task_id: str | None = None
        offset: int = Field(default=0, ge=0)
        limit: int = Field(default=16384, gt=0, le=1024 * 1024)
        wait_ms: int = Field(default=10000, ge=0, le=300000)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.MANAGE_SHELL,
            type="function",
            description=load_desc(Path(__file__).parent / "manage_shell_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "output", "wait", "stop"]},
                    "task_id": {
                        "type": "string",
                        "description": "Required except for list; task IDs survive context compression.",
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "default": 0,
                        "description": "Byte offset from the previous next_offset.",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1048576, "default": 16384},
                    "wait_ms": {"type": "integer", "minimum": 0, "maximum": 300000, "default": 10000},
                },
                "required": ["action"],
            },
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        manager = context.shell_task_manager
        if manager is None:
            return message.ToolResultMessage(
                status="error", output_text="Managed shell tasks are unavailable without the server-owned manager."
            )
        try:
            args = cls.Arguments.model_validate_json(arguments)
            tasks = await manager.list_tasks(context.session_id, work_dir=context.work_dir)
            if args.action == "list":
                output = "\n".join(_format_task(task) for task in tasks) or "No background shell tasks."
                ui_extra = ShellTaskUIExtra(action=args.action, tasks=tasks)
            else:
                if not args.task_id:
                    raise ValueError("task_id is required for output, wait, and stop")
                if args.action == "output":
                    page = await manager.read_output(
                        context.session_id, args.task_id, offset=args.offset, limit=args.limit
                    )
                    output = (
                        f"{_format_task(page.task)}\n"
                        f"next_offset={page.next_offset}; truncated={str(page.truncated).lower()}\n"
                        + (f"Output:\n{page.output}" if page.output else "No output available.")
                    )
                    ui_extra = ShellTaskUIExtra(
                        action=args.action,
                        tasks=[page.task],
                        output=page.output,
                        next_offset=page.next_offset,
                        truncated=page.truncated,
                    )
                elif args.action == "wait":
                    task = await manager.wait_task(context.session_id, args.task_id, wait_ms=args.wait_ms)
                    output = _format_task(task)
                    ui_extra = ShellTaskUIExtra(action=args.action, tasks=[task])
                else:
                    task = await manager.stop_task(context.session_id, args.task_id)
                    output = _format_task(task)
                    ui_extra = ShellTaskUIExtra(action=args.action, tasks=[task])
            return message.ToolResultMessage(status="success", output_text=output, ui_extra=ui_extra)
        except (ValueError, OSError) as error:
            return message.ToolResultMessage(status="error", output_text=f"ManageShell error: {error}")
