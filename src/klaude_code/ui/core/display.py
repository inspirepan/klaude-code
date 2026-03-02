from abc import ABC, abstractmethod
from asyncio import Queue

from klaude_code.log import log
from klaude_code.protocol import events


class DisplayABC(ABC):
    """
    Abstract base class for UI display implementations.

    A Display is responsible for rendering event envelopes from the runtime to the user.
    Implementations can range from minimal text output to rich interactive
    terminals (TUIDisplay).

    Lifecycle:
        1. start() is called once before any events are consumed.
        2. consume_envelope() is called for each envelope from the runtime.
        3. stop() is called once when the display is shutting down (after EndEvent).

    Typical Usage:
        # See klaude_code.tui.display.TUIDisplay for the interactive terminal frontend.
        await display.consume_event_loop(envelope_queue)

        # Or manually:
        await display.start()
        try:
            async for envelope in events:
                if isinstance(envelope.event, EndEvent):
                    break
                await display.consume_envelope(envelope)
        finally:
            await display.stop()

    Thread Safety:
        Display implementations should be used from a single async task.
        The consume_event_loop method handles the standard event loop pattern.
    """

    @abstractmethod
    async def consume_envelope(self, envelope: events.EventEnvelope) -> None:
        """
        Process a single event envelope from the runtime.

        This method is called for each envelope except EndEvent, which triggers stop().
        Implementations should handle all relevant event types and render them
        appropriately for the user.

        Args:
            envelope: The event envelope to process.
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

    async def consume_event_loop(self, q: Queue[events.EventEnvelope]) -> None:
        """
        Main event loop that processes event envelopes from a queue.

        This is the standard entry point for running a display. It handles:
        - Calling start() before processing
        - Consuming envelopes until EndEvent is received
        - Calling stop() after EndEvent
        - Error handling and logging for individual events

        Args:
            q: An asyncio Queue of event envelopes to process. The loop exits when
               an EndEvent is received.
        """
        await self.start()
        while True:
            envelope = await q.get()
            try:
                if isinstance(envelope.event, events.EndEvent):
                    await self.stop()
                    break
                await self.consume_envelope(envelope)
            except Exception as e:
                import traceback

                log(
                    f"Error in consume_event_loop, {e.__class__.__name__}, {e}",
                    style="red",
                )
                log(traceback.format_exc(), style="red")
            finally:
                q.task_done()
