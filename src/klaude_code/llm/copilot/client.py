import json
from typing import override

import anthropic
import httpx
import openai
from anthropic import APIError
from anthropic.types.beta.beta_tool_choice_auto_param import BetaToolChoiceAutoParam
from anthropic.types.beta.message_create_params import MessageCreateParamsStreaming
from openai import AsyncOpenAI
from openai.types.responses.response_create_params import ResponseCreateParamsStreaming

from klaude_code.auth.copilot.exceptions import CopilotNotLoggedInError
from klaude_code.auth.copilot.oauth import COPILOT_STATIC_HEADERS, CopilotOAuth
from klaude_code.auth.copilot.token_manager import CopilotTokenManager
from klaude_code.const import (
    ANTHROPIC_BETA_INTERLEAVED_THINKING,
    DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    LLM_HTTP_TIMEOUT_CONNECT,
    LLM_HTTP_TIMEOUT_READ,
    LLM_HTTP_TIMEOUT_TOTAL,
)
from klaude_code.llm.anthropic.client import AnthropicLLMStream
from klaude_code.llm.anthropic.input import (
    convert_history_to_input as convert_anthropic_history_to_input,
)
from klaude_code.llm.anthropic.input import (
    convert_system_to_input,
)
from klaude_code.llm.anthropic.input import (
    convert_tool_schema as convert_anthropic_tool_schema,
)
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_responses.client import ResponsesLLMStream
from klaude_code.llm.openai_responses.input import (
    convert_history_to_input as convert_responses_history_to_input,
)
from klaude_code.llm.openai_responses.input import (
    convert_tool_schema as convert_responses_tool_schema,
)
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.model_id import is_claude_model_any, supports_adaptive_thinking


def _is_copilot_anthropic_model(model_id: str | None) -> bool:
    return is_claude_model_any(model_id)


def _build_responses_payload(param: llm_param.LLMCallParameter) -> ResponseCreateParamsStreaming:
    """Build Copilot Responses API request payload."""
    inputs = convert_responses_history_to_input(param.input, param.model_id)
    tools = convert_responses_tool_schema(param.tools)

    payload: ResponseCreateParamsStreaming = {
        "model": str(param.model_id),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "include": ["reasoning.encrypted_content"],
        "store": False,
        "stream": True,
        "input": inputs,
        "instructions": param.system,
        "tools": tools,
        "prompt_cache_key": param.session_id or "",
        # max_output_token and temperature are not supported by Copilot codex-style endpoint.
    }

    if param.thinking and param.thinking.reasoning_effort:
        payload["reasoning"] = {
            "effort": param.thinking.reasoning_effort,
            "summary": param.thinking.reasoning_summary,
        }

    if param.verbosity:
        payload["text"] = {"verbosity": param.verbosity}  # type: ignore[typeddict-item]

    return payload


def _build_anthropic_payload(param: llm_param.LLMCallParameter) -> MessageCreateParamsStreaming:
    """Build Copilot Anthropic Messages API request payload."""
    messages_input = convert_anthropic_history_to_input(param.input, param.model_id)
    tools = convert_anthropic_tool_schema(param.tools)
    system_messages = [msg for msg in param.input if isinstance(msg, message.SystemMessage)]
    system = convert_system_to_input(param.system, system_messages)

    tool_choice: BetaToolChoiceAutoParam = {
        "type": "auto",
        "disable_parallel_tool_use": False,
    }

    betas: list[str] = []
    if param.thinking and param.thinking.type in ("enabled", "adaptive"):
        is_builtin_adaptive = supports_adaptive_thinking(str(param.model_id)) and param.thinking.type == "adaptive"
        if not is_builtin_adaptive:
            betas = [ANTHROPIC_BETA_INTERLEAVED_THINKING]

    payload: MessageCreateParamsStreaming = {
        "model": str(param.model_id),
        "tool_choice": tool_choice,
        "stream": True,
        "max_tokens": param.max_tokens or DEFAULT_MAX_TOKENS,
        "temperature": param.temperature or DEFAULT_TEMPERATURE,
        "messages": messages_input,
        "system": system,
        "tools": tools,
        "betas": betas,
    }

    if param.thinking and param.thinking.type == "adaptive":
        payload["thinking"] = {"type": "adaptive"}  # type: ignore[typeddict-item]
    elif param.thinking and param.thinking.type == "enabled":
        payload["thinking"] = anthropic.types.ThinkingConfigEnabledParam(
            type="enabled",
            budget_tokens=param.thinking.budget_tokens or DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS,
        )

    if param.verbosity:
        payload["output_config"] = {"effort": param.verbosity}  # type: ignore[typeddict-item]

    return payload


def _infer_copilot_initiator(messages: list[message.Message]) -> str:
    if not messages:
        return "user"
    last = messages[-1]
    return "agent" if last.role != "user" else "user"


def _has_copilot_vision_input(messages: list[message.Message]) -> bool:
    for msg in messages:
        if isinstance(msg, (message.UserMessage, message.ToolResultMessage)) and any(
            isinstance(part, (message.ImageURLPart, message.ImageFilePart)) for part in msg.parts
        ):
            return True
    return False


def _build_copilot_dynamic_headers(param: llm_param.LLMCallParameter) -> dict[str, str]:
    headers: dict[str, str] = {
        "X-Initiator": _infer_copilot_initiator(param.input),
        "Openai-Intent": "conversation-edits",
    }
    if _has_copilot_vision_input(param.input):
        headers["Copilot-Vision-Request"] = "true"
    session_id = param.session_id or ""
    if session_id:
        headers["conversation_id"] = session_id
        headers["session_id"] = session_id
    return headers


@register(llm_param.LLMClientProtocol.COPILOT_OAUTH)
class CopilotClient(LLMClientABC):
    """LLM client for GitHub Copilot using OAuth device flow."""

    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        self._token_manager = CopilotTokenManager()
        self._oauth = CopilotOAuth(self._token_manager)

        if not self._token_manager.is_logged_in():
            raise CopilotNotLoggedInError("Copilot authentication required. Run 'klaude login copilot' first.")

        self._openai_client: AsyncOpenAI | None = None
        self._anthropic_client: anthropic.AsyncAnthropic | None = None
        self._access_token: str | None = None
        self._base_url: str | None = None

    def _create_openai_client(self, *, token: str, base_url: str) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=token,
            base_url=base_url,
            timeout=httpx.Timeout(LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ),
            default_headers={
                **COPILOT_STATIC_HEADERS,
                "OpenAI-Beta": "responses=experimental",
            },
        )

    def _create_anthropic_client(self, *, token: str, base_url: str) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(
            auth_token=token,
            base_url=base_url,
            timeout=httpx.Timeout(LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ),
            default_headers={
                **COPILOT_STATIC_HEADERS,
            },
        )

    def _ensure_clients(self) -> None:
        token, base_url = self._oauth.ensure_valid_token()
        if (
            token == self._access_token
            and base_url == self._base_url
            and self._openai_client
            and self._anthropic_client
        ):
            return

        self._access_token = token
        self._base_url = base_url
        self._openai_client = self._create_openai_client(token=token, base_url=base_url)
        self._anthropic_client = self._create_anthropic_client(token=token, base_url=base_url)

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self._ensure_clients()
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)
        extra_headers = _build_copilot_dynamic_headers(param)

        if _is_copilot_anthropic_model(param.model_id):
            payload = _build_anthropic_payload(param)
            log_debug(
                json.dumps(payload, ensure_ascii=False, default=str),
                style="yellow",
                debug_type=DebugType.LLM_PAYLOAD,
            )
            try:
                anthropic_client = self._anthropic_client
                if anthropic_client is None:
                    return error_llm_stream(
                        metadata_tracker, error="RuntimeError Copilot Anthropic client not initialized"
                    )
                stream = anthropic_client.beta.messages.create(
                    **payload,
                    extra_headers=extra_headers,
                )
                return AnthropicLLMStream(stream, param=param, metadata_tracker=metadata_tracker)
            except (APIError, httpx.HTTPError) as e:
                error_message = f"{e.__class__.__name__} {e!s}"
                return error_llm_stream(metadata_tracker, error=error_message)

        payload = _build_responses_payload(param)
        log_debug(
            json.dumps(payload, ensure_ascii=False, default=str),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )
        try:
            openai_client = self._openai_client
            if openai_client is None:
                return error_llm_stream(metadata_tracker, error="RuntimeError Copilot OpenAI client not initialized")
            stream = await openai_client.responses.create(
                **payload,
                extra_headers=extra_headers,
            )
        except (openai.OpenAIError, httpx.HTTPError) as e:
            error_message = f"{e.__class__.__name__} {e!s}"
            return error_llm_stream(metadata_tracker, error=error_message)

        return ResponsesLLMStream(stream, param=param, metadata_tracker=metadata_tracker)
