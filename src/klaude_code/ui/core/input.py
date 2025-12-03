from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from klaude_code.protocol.model import UserInputPayload


class InputProviderABC(ABC):
    """
    Abstract base class for user input providers.

    An InputProvider is responsible for collecting user input and yielding it
    to the application. Implementations handle the specifics of input collection,
    such as terminal readline, prompt-toolkit sessions, or other input sources.

    Lifecycle:
        1. start() is called once before any inputs are requested.
        2. iter_inputs() yields user input strings until the user exits.
        3. stop() is called once when input collection is complete.

    Typical Usage:
        input_provider = PromptToolkitInput(status_provider=my_status_fn)
        await input_provider.start()
        try:
            async for user_input in input_provider.iter_inputs():
                if user_input.text.strip().lower() in {"exit", "quit"}:
                    break
                # Process user_input.text and user_input.images...
        finally:
            await input_provider.stop()

    Thread Safety:
        Input providers should be used from a single async task.
    """

    @abstractmethod
    async def start(self) -> None:
        """
        Initialize the input provider before reading inputs.

        Called once before iter_inputs(). Use this for any setup that needs
        to happen before input collection begins (e.g., configuring terminal
        settings, loading history).
        """

    @abstractmethod
    async def stop(self) -> None:
        """
        Clean up the input provider after input collection is complete.

        Called once after iter_inputs() finishes. Use this for cleanup such
        as saving history, restoring terminal state, or releasing resources.
        """

    @abstractmethod
    async def iter_inputs(self) -> AsyncIterator[UserInputPayload]:
        """
        Yield user input payloads asynchronously.

        This is the main method for collecting user input. Each yield returns
        one complete user input payload containing text and optional images
        (e.g., after the user presses Enter). The iterator completes when the
        user signals end of input (e.g., Ctrl+D) or when the application
        requests shutdown.

        Yields:
            UserInputPayload with text and optional images.
        """
        raise NotImplementedError
        yield UserInputPayload(text="")
