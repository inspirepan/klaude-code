import sys
from typing import override

from klaude_code.protocol import events
from klaude_code.ui.core.display import DisplayABC


class ExecDisplay(DisplayABC):
    """A display implementation for exec mode - only handles TaskFinishEvent."""

    @override
    async def consume_event(self, event: events.Event) -> None:
        """Only handle TaskFinishEvent."""
        match event:
            case events.TaskStartEvent():
                pass
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


class StreamJsonDisplay(DisplayABC):
    """A display implementation that streams all events as JSON lines."""

    @override
    async def consume_event(self, event: events.Event) -> None:
        """Stream each event as a JSON line."""
        if isinstance(event, events.EndEvent):
            return
        event_type = type(event).__name__
        json_data = event.model_dump_json()
        # Output format: {"type": "EventName", "data": {...}}
        print(f'{{"type": "{event_type}", "data": {json_data}}}', flush=True)
        sys.stdout.flush()

    @override
    async def start(self) -> None:
        """Do nothing on start."""
        pass

    @override
    async def stop(self) -> None:
        """Do nothing on stop."""
        pass
