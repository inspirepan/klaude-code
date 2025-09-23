from typing import override

from codex_mini.protocol import events
from codex_mini.ui.display_abc import DisplayABC


class ExecDisplay(DisplayABC):
    """A display implementation for exec mode - only handles TaskFinishEvent."""

    @override
    async def consume_event(self, event: events.Event) -> None:
        """Only handle TaskFinishEvent."""
        match event:
            case events.ErrorEvent() as e:
                print(f"Error: {e.error_message}")
            case events.TaskFinishEvent() as e:
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
