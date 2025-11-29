from abc import ABC, abstractmethod
from asyncio import Queue

from klaude_code.protocol import events
from klaude_code.trace import log


class DisplayABC(ABC):
    """
    Abstract base class for UI display implementations.

    A Display is responsible for rendering events from the executor to the user.
    Implementations can range from simple text output (ExecDisplay) to rich
    interactive terminals (REPLDisplay) or debugging wrappers (DebugEventDisplay).

    Lifecycle:
        1. start() is called once before any events are consumed.
        2. consume_event() is called for each event from the executor.
        3. stop() is called once when the display is shutting down (after EndEvent).

    Typical Usage:
        display = create_default_display()
        await display.consume_event_loop(event_queue)

        # Or manually:
        await display.start()
        try:
            async for event in events:
                if isinstance(event, EndEvent):
                    break
                await display.consume_event(event)
        finally:
            await display.stop()

    Thread Safety:
        Display implementations should be used from a single async task.
        The consume_event_loop method handles the standard event loop pattern.
    """

    @abstractmethod
    async def consume_event(self, event: events.Event) -> None:
        """
        Process a single event from the executor.

        This method is called for each event except EndEvent, which triggers stop().
        Implementations should handle all relevant event types and render them
        appropriately for the user.

        Args:
            event: The event to process. See klaude_code.protocol.events for types.
        """

    @abstractmethod
    async def start(self) -> None:
        """
        Initialize the display before processing events.

        Called once before any consume_event calls. Use this for any setup
        that needs to happen before rendering begins (e.g., initializing
        terminal state, starting background tasks).
        """

    @abstractmethod
    async def stop(self) -> None:
        """
        Clean up the display after all events have been processed.

        Called once after EndEvent is received. Use this for cleanup such as
        stopping spinners, restoring terminal state, or flushing output buffers.
        """

    async def consume_event_loop(self, q: Queue[events.Event]) -> None:
        """
        Main event loop that processes events from a queue.

        This is the standard entry point for running a display. It handles:
        - Calling start() before processing
        - Consuming events until EndEvent is received
        - Calling stop() after EndEvent
        - Error handling and logging for individual events

        Args:
            q: An asyncio Queue of events to process. The loop exits when
               an EndEvent is received.
        """
        await self.start()
        while True:
            event = await q.get()
            try:
                if isinstance(event, events.EndEvent):
                    await self.stop()
                    break
                await self.consume_event(event)
            except Exception as e:
                import traceback

                log(
                    f"Error in consume_event_loop, {e.__class__.__name__}, {e}",
                    style="red",
                )
                log(traceback.format_exc(), style="red")
            finally:
                q.task_done()
