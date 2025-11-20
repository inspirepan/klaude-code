from typing import override

from klaude_code.protocol import events
from klaude_code.ui.base.display_abc import DisplayABC
from klaude_code.ui.base.progress_bar import OSC94States, emit_osc94


class ExecDisplay(DisplayABC):
    """A display implementation for exec mode - only handles TaskFinishEvent."""

    @override
    async def consume_event(self, event: events.Event) -> None:
        """Only handle TaskFinishEvent."""
        match event:
            case events.TaskStartEvent():
                emit_osc94(OSC94States.INDETERMINATE)
            case events.ErrorEvent() as e:
                emit_osc94(OSC94States.HIDDEN)
                print(f"Error: {e.error_message}")
            case events.TaskFinishEvent() as e:
                emit_osc94(OSC94States.HIDDEN)
                # Print the task result when task finishes
                if e.task_result.strip():
                    print(e.task_result)
            case _:
                # Ignore all other events
                pass

    @override
    async def start(self) -> None:
        """Do nothing on start."""
        pass

    @override
    async def stop(self) -> None:
        """Do nothing on stop."""
        pass
