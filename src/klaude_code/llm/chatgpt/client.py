"""LLM client for the OpenAI Responses API with a ChatGPT subscription."""

import asyncio
from typing import Any, cast, override

import httpx
import openai
from openai import AsyncOpenAI
from openai.types.responses.response_create_params import Reasoning, ResponseCreateParamsBase

from klaude_code.auth.chatgpt.exceptions import ChatGPTNotLoggedInError
from klaude_code.auth.chatgpt.oauth import ChatGPTOAuth
from klaude_code.auth.chatgpt.token_manager import ChatGPTTokenManager
from klaude_code.const import CHATGPT_API_BASE_URL, CHATGPT_USAGE_LIMIT_CODES, CHATGPT_USAGE_SETTINGS_URL
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.http import create_async_http_client, create_http_timeout
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_responses.client import ResponsesLLMStream
from klaude_code.llm.openai_responses.input import convert_history_to_input, convert_tool_schema
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, debug_json, log_debug
from klaude_code.protocol import llm_param
from klaude_code.protocol.system_prompt import strip_system_prompt_boundary

CHATGPT_USER_AGENT = "klaude-code/2"
# OpenAI rejects prompt_cache_key values longer than 64 characters.
PROMPT_CACHE_KEY_MAX_LENGTH = 64


def cache_affinity_id(param: llm_param.LLMCallParameter) -> str | None:
    """Single cache-affinity identity for the payload key and session headers."""
    key = param.prompt_cache_key or param.session_id
    if not key:
        return None
    return key[:PROMPT_CACHE_KEY_MAX_LENGTH]


def build_payload(param: llm_param.LLMCallParameter) -> ResponseCreateParamsBase:
    """Build request parameters for ChatGPT plan usage."""
    inputs = convert_history_to_input(param.input, param.model_id)
    tools = convert_tool_schema(param.tools)

    payload: ResponseCreateParamsBase = {
        "model": str(param.model_id),
        "store": False,
        "input": inputs,
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "include": [
            "reasoning.encrypted_content",
        ],
        # max_output_tokens and temperature are not supported on this route.
    }

    instructions = strip_system_prompt_boundary(param.system)
    if instructions:
        payload["instructions"] = instructions

    affinity_id = cache_affinity_id(param)
    if affinity_id:
        payload["prompt_cache_key"] = affinity_id

    verbosity = "high" if param.verbosity == "max" else (param.verbosity or "low")
    payload["text"] = {"verbosity": verbosity}  # type: ignore[typeddict-item]

    if param.fast_mode:
        payload["service_tier"] = "priority"

    if tools:
        payload["tools"] = tools

    if param.thinking and (
        param.thinking.reasoning_effort or param.thinking.reasoning_mode or param.thinking.reasoning_context
    ):
        effort = param.thinking.reasoning_effort
        model_id = str(param.model_id)
        if (model_id.startswith("gpt-5.2") or model_id.startswith("gpt-5.3")) and effort == "minimal":
            effort = "low"
        if model_id == "gpt-5.1" and effort == "xhigh":
            effort = "high"
        if model_id == "gpt-5.1-codex-mini" and effort in {"high", "xhigh"}:
            effort = "high"
        if model_id == "gpt-5.1-codex-mini" and effort in {"none", "minimal", "low"}:
            effort = "medium"
        # GPT-6 dropped the two lowest tiers that GPT-5.6 still accepted.
        if model_id.startswith("gpt-6") and effort in {"none", "minimal"}:
            effort = "low"
        reasoning: dict[str, Any] = {"summary": param.thinking.reasoning_summary or "auto"}
        if effort:
            reasoning["effort"] = effort
        if param.thinking.reasoning_mode:
            reasoning["mode"] = param.thinking.reasoning_mode
        if param.thinking.reasoning_context:
            reasoning["context"] = param.thinking.reasoning_context
        payload["reasoning"] = cast(Reasoning, reasoning)

    return payload


def _usage_limit_message(error: Exception) -> str:
    text = str(error)
    if any(code in text for code in CHATGPT_USAGE_LIMIT_CODES):
        return f"{text}\nChatGPT plan usage limit reached. Manage usage at {CHATGPT_USAGE_SETTINGS_URL}"
    return text


@register(llm_param.LLMClientProtocol.CHATGPT_OAUTH)
class ChatGPTClient(LLMClientABC):
    """LLM client for ChatGPT plan usage through the OpenAI Responses API."""

    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        self._token_manager = ChatGPTTokenManager()
        self._oauth = ChatGPTOAuth(self._token_manager)

        if not self._token_manager.is_logged_in():
            raise ChatGPTNotLoggedInError("ChatGPT authentication required. Run 'klaude auth login chatgpt' first.")

        self.client = self._create_client()

    def _create_client(self) -> AsyncOpenAI:
        """Create the OpenAI client with the stored OAuth access token."""
        state = self._token_manager.get_state()
        if state is None:
            raise ChatGPTNotLoggedInError("Not signed in with ChatGPT. Run 'klaude auth login chatgpt' first.")

        return AsyncOpenAI(
            api_key=state.access_token,
            base_url=CHATGPT_API_BASE_URL,
            max_retries=0,
            timeout=create_http_timeout(),
            http_client=create_async_http_client(),
            default_headers={
                "User-Agent": CHATGPT_USER_AGENT,
                "Accept": "text/event-stream",
            },
        )

    def _ensure_valid_token(self) -> None:
        """Ensure the token is valid, refreshing if needed."""
        state = self._token_manager.get_state()
        if state is None:
            raise ChatGPTNotLoggedInError("Not signed in with ChatGPT. Run 'klaude auth login chatgpt' first.")

        if state.is_expired():
            self._oauth.refresh()
            self.client = self._create_client()

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self._ensure_valid_token()

        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        # Payload building re-encodes history images; keep it off the event loop.
        payload = await asyncio.to_thread(build_payload, param)
        extra_headers: dict[str, str] = {}
        affinity_id = cache_affinity_id(param)
        if affinity_id:
            extra_headers["session_id"] = affinity_id
            extra_headers["x-client-request-id"] = affinity_id

        log_debug(
            lambda: debug_json(payload),
            debug_type=DebugType.LLM_PAYLOAD,
        )
        try:
            stream = await self.client.responses.create(
                **payload,
                stream=True,
                extra_headers=extra_headers,
            )
        except (openai.OpenAIError, httpx.HTTPError) as e:
            return error_llm_stream(metadata_tracker, error=_usage_limit_message(e))

        return ResponsesLLMStream(stream, param=param, metadata_tracker=metadata_tracker)
