import asyncio
import os
import time
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Optional, Tuple

import anthropic
import openai
from rich.console import Group
from rich.text import Text

from ..config.simple import NO_STREAM_PRINT, SimpleConfig
from ..message import AIMessage, BasicMessage
from ..tool import Tool
from ..tui import (
    INTERRUPT_TIP,
    ColorStyle,
    CropAboveLive,
    console,
    render_dot_status,
    render_suffix,
)
from ..tui.stream_status import (
    StreamStatus,
    get_content_status_text,
    get_reasoning_status_text,
    get_tool_call_status_text,
    get_upload_status_text,
    text_status_str,
)
from ..utils.exception import format_exception
from .config import TIMEOUT
from .llm_proxy_anthropic import AnthropicProxy
from .llm_proxy_base import DEFAULT_RETRIES, DEFAULT_RETRY_BACKOFF_BASE, LLMProxyBase
from .llm_proxy_gemini import GeminiProxy
from .llm_proxy_glm import GLMProxy
from .llm_proxy_openai import OpenAIProxy

NON_RETRY_EXCEPTIONS = (
    KeyboardInterrupt,
    asyncio.CancelledError,
    # LLM Errors
    openai.BadRequestError,
    anthropic.BadRequestError,
    openai.AuthenticationError,
    anthropic.AuthenticationError,
    openai.PermissionDeniedError,
    anthropic.PermissionDeniedError,
    openai.NotFoundError,
    anthropic.NotFoundError,
    openai.ConflictError,
    anthropic.ConflictError,
    openai.UnprocessableEntityError,
    anthropic.UnprocessableEntityError,
)


class LLMClientWrapper(ABC):
    """Base class for LLM client wrappers that provides common interface for different client decorators"""

    def __init__(self, client: LLMProxyBase):
        """Initialize wrapper with the underlying LLM client

        Args:
            client: The base LLM proxy client to wrap
        """
        self.client = client

    @property
    def model_name(self) -> str:
        return self.client.model_name

    @abstractmethod
    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = TIMEOUT,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        """Stream LLM response with status updates

        Args:
            msgs: List of messages to send to the LLM
            tools: Optional list of tools available to the LLM
            timeout: Request timeout in seconds

        Yields:
            Tuple of (StreamStatus, AIMessage) for each streaming update
        """
        pass


class RetryWrapper(LLMClientWrapper):
    """Wrapper that adds exponential backoff retry logic to LLM calls

    Retries failed requests with exponential backoff, but skips certain non-retryable
    exceptions like authentication errors and user interruptions.
    """

    def __init__(
        self,
        client: LLMProxyBase,
        max_retries: int = DEFAULT_RETRIES,
        backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE,
    ):
        """Initialize retry wrapper

        Args:
            client: The LLM client to wrap with retry logic
            max_retries: Maximum number of retry attempts
            backoff_base: Base delay for exponential backoff (in seconds)
        """
        super().__init__(client)
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = TIMEOUT,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                async for item in self.client.stream_call(msgs, tools, timeout):
                    yield item
                return
            except NON_RETRY_EXCEPTIONS as e:
                raise e
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self.backoff_base * (2**attempt)
                    error_text = Text.assemble(
                        format_exception(last_exception),
                        (" · Retrying in ", "default"),
                        (f"{delay:.1f}", "default"),
                        (" seconds... (attempt ", "default"),
                        (f"{attempt + 1}/{self.max_retries}", "default"),
                        (")", "default"),
                    )
                    error_msg = error_text.plain
                    error_msg = self.enhance_error_message(e, error_msg)

                    console.print(
                        render_suffix(
                            error_msg,
                            style=ColorStyle.ERROR,
                        )
                    )
                    await asyncio.sleep(delay)
        # All retries exhausted, raise the last exception
        raise last_exception

    def enhance_error_message(self, exception, error_msg: str) -> str:
        if isinstance(
            exception, (openai.APIConnectionError, anthropic.APIConnectionError)
        ):
            if (
                os.environ.get("http_proxy")
                or os.environ.get("https_proxy")
                or os.environ.get("HTTP_PROXY")
                or os.environ.get("HTTPS_PROXY")
            ):
                error_msg += " · HTTP proxy detected, try disabling it"
        return error_msg


class DisplayWrapper(LLMClientWrapper):
    """Wrapper that adds real-time status display and progress indicators to LLM calls

    Provides visual feedback to users about the current phase of LLM processing,
    including thinking, content generation, tool calls, and file uploads.
    """

    def __init__(self, client: LLMProxyBase):
        """Initialize status wrapper

        Args:
            client: The LLM client to wrap with status display
        """
        super().__init__(client)

    def _get_phase_indicator_and_status(
        self,
        stream_status: StreamStatus,
        reasoning_status_text: str,
        content_status_text: str,
        upload_status_text: str,
        status_text_seed: int,
    ) -> Tuple[str, str]:
        if stream_status.phase == "tool_call":
            indicator = "⚒"
            if stream_status.tool_names:
                current_status_text = get_tool_call_status_text(
                    stream_status.tool_names[-1], status_text_seed
                )
            else:
                current_status_text = reasoning_status_text
        elif stream_status.phase == "upload":
            indicator = ""
            current_status_text = upload_status_text
        elif stream_status.phase == "think":
            indicator = "✻"
            current_status_text = reasoning_status_text
        elif stream_status.phase == "content":
            indicator = "↓"
            current_status_text = content_status_text
        else:
            indicator = ""
            current_status_text = reasoning_status_text

        return indicator, current_status_text

    def _update_status_display(
        self, status, indicator: str, tokens: int, current_status_text: str
    ):
        """Update the live status display with current progress information

        Args:
            status: The status object to update
            indicator: Phase indicator emoji
            tokens: Number of tokens processed so far
            current_status_text: Text describing current activity
        """
        status.update(
            status=current_status_text,
            description=Text.assemble(
                (f"{indicator}", ColorStyle.SUCCESS),
                (f" {tokens} tokens" if tokens else "", ColorStyle.SUCCESS),
                (INTERRUPT_TIP, ColorStyle.HINT),
            ),
        )

    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = TIMEOUT,
        status_text: Optional[str] = None,
        show_result: bool = True,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        status_text_seed = int(time.time() * 1000) % 10000
        if status_text:
            reasoning_status_text = text_status_str(status_text)
            content_status_text = text_status_str(status_text)
            upload_status_text = text_status_str(status_text)
        else:
            reasoning_status_text = get_reasoning_status_text(status_text_seed)
            content_status_text = get_content_status_text(status_text_seed)
            upload_status_text = get_upload_status_text(status_text_seed)

        print_content_flag = False
        print_thinking_flag = False

        current_status_text = upload_status_text

        status = render_dot_status(current_status_text)

        stream_print_result = not SimpleConfig.get(NO_STREAM_PRINT, False)

        if stream_print_result:
            live = CropAboveLive(
                status, refresh_per_second=10, console=console.console, transient=True
            )
        else:
            # Use static status display
            live = status

        with live:
            async for stream_status, ai_message in self.client.stream_call(
                msgs, tools, timeout
            ):
                ai_message: AIMessage
                stream_status: StreamStatus
                indicator, current_status_text = self._get_phase_indicator_and_status(
                    stream_status,
                    reasoning_status_text,
                    content_status_text,
                    upload_status_text,
                    status_text_seed,
                )
                self._update_status_display(
                    status, indicator, stream_status.tokens, current_status_text
                )

                if show_result:
                    if stream_print_result:
                        if (
                            ai_message.content.strip()
                            or ai_message.thinking_content.strip()
                        ):
                            # Group content with status, adding spacing for readability
                            live.update(Group("", ai_message, status))
                        else:
                            # Only show status if no content yet
                            live.update(status)
                    else:
                        if (
                            stream_status.phase in ["tool_call", "completed"]
                            and not print_content_flag
                            and ai_message.content
                        ):
                            console.print()
                            console.print(*ai_message.get_content_renderable(done=True))
                            print_content_flag = True
                        if (
                            stream_status.phase in ["content", "tool_call", "completed"]
                            and not print_thinking_flag
                            and ai_message.thinking_content
                        ):
                            console.print()
                            console.print(*ai_message.get_thinking_renderable())
                            print_thinking_flag = True
                yield stream_status, ai_message

            # Clean up the live display area
            if stream_print_result:
                live.update("")

        # Final output since transient=True clears the live area
        # Re-print the final message for persistence
        if (
            show_result
            and stream_print_result
            and (ai_message.content or ai_message.thinking_content)
        ):
            console.print()
            console.print(ai_message)


class LLMClient:
    """High-level LLM client that automatically selects the appropriate provider and adds retry/status functionality

    This is the main entry point for LLM interactions. It automatically detects the provider
    based on the model name and base URL, then wraps the client with retry logic.
    """

    def __init__(
        self,
        model_name: str,
        base_url: str,
        api_key: str,
        model_azure: bool,
        max_tokens: int,
        extra_header: dict,
        extra_body: dict,
        enable_thinking: bool,
        api_version: str,
        max_retries=DEFAULT_RETRIES,
        backoff_base=DEFAULT_RETRY_BACKOFF_BASE,
    ):
        """Initialize LLM client with provider auto-detection

        Args:
            model_name: Name of the model to use
            base_url: API base URL for the provider
            api_key: API key for authentication
            model_azure: Whether to use Azure OpenAI configuration
            max_tokens: Maximum tokens for responses
            extra_header: Additional HTTP headers
            extra_body: Additional request body parameters
            enable_thinking: Whether to enable thinking/reasoning mode
            api_version: API version for Azure deployments
            max_retries: Maximum number of retry attempts
            backoff_base: Base delay for exponential backoff
        """
        # Auto-detect provider based on base URL and model name
        if base_url == "https://api.anthropic.com/v1/":
            base_client = AnthropicProxy(
                model_name,
                api_key,
                max_tokens,
                enable_thinking,
                extra_header,
                extra_body,
            )
        elif "gemini" in model_name.lower():
            base_client = GeminiProxy(
                model_name,
                base_url,
                api_key,
                model_azure,
                max_tokens,
                extra_header,
                extra_body,
                api_version,
                enable_thinking,
            )
        elif "glm" in model_name.lower():
            base_client = GLMProxy(
                model_name,
                base_url,
                api_key,
                model_azure,
                max_tokens,
                extra_header,
                extra_body,
                api_version,
                enable_thinking,
            )
        else:
            base_client = OpenAIProxy(
                model_name,
                base_url,
                api_key,
                model_azure,
                max_tokens,
                extra_header,
                extra_body,
                api_version,
                enable_thinking,
            )

        self.client = RetryWrapper(base_client, max_retries, backoff_base)

    @property
    def model_name(self) -> str:
        return self.client.model_name

    def cancel(self):
        """Cancel the current request"""
        # Find the base client and cancel it
        current_client = self.client
        while hasattr(current_client, "client"):
            current_client = current_client.client
        if hasattr(current_client, "cancel"):
            current_client.cancel()

    async def call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        show_status: bool = True,
        show_result: bool = True,
        status_text: Optional[str] = None,
        timeout: float = TIMEOUT,
    ) -> AIMessage:
        if not show_status:
            async for _, ai_message in self.client.stream_call(
                msgs, tools, timeout=timeout
            ):
                pass
            return ai_message

        async for _, ai_message in DisplayWrapper(self.client).stream_call(
            msgs,
            tools,
            timeout=timeout,
            status_text=status_text,
            show_result=show_result,
        ):
            pass
        return ai_message
