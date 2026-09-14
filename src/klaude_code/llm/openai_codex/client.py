"""Codex LLM client using ChatGPT subscription via OAuth."""

import asyncio
from typing import Any, cast, override

import httpx
import openai
from openai import AsyncOpenAI
from openai.types.responses.response_create_params import Reasoning, ResponseCreateParamsBase

from klaude_code.auth.codex.exceptions import CodexNotLoggedInError
from klaude_code.auth.codex.oauth import CodexOAuth
from klaude_code.auth.codex.token_manager import CodexTokenManager
from klaude_code.const import (
    CODEX_BASE_URL,
    CODEX_USER_AGENT,
)
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

# OpenAI rejects prompt_cache_key values longer than 64 characters.
PROMPT_CACHE_KEY_MAX_LENGTH = 64


def cache_affinity_id(param: llm_param.LLMCallParameter) -> str | None:
    """Single cache-affinity identity for the payload key and session headers.

    Forked/cache-safe call paths inherit the parent's ``prompt_cache_key``
    while getting a fresh session id; pi ties ``prompt_cache_key`` and the
    session-affinity headers to one value, so do the same here.
    """
    key = param.prompt_cache_key or param.session_id
    if not key:
        return None
    return key[:PROMPT_CACHE_KEY_MAX_LENGTH]


def build_payload(param: llm_param.LLMCallParameter) -> ResponseCreateParamsBase:
    """Build Codex API request parameters."""
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
        # max_output_token and temperature is not supported in Codex API
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


CODEX_HEADERS = {
    "originator": "pi",
    "User-Agent": CODEX_USER_AGENT,
    "OpenAI-Beta": "responses=experimental",
    "Accept": "text/event-stream",
}


async def strip_stainless_headers(request: httpx.Request) -> None:
    """Drop the openai SDK's X-Stainless-* telemetry headers.

    The reference Codex OAuth clients (pi, codex CLI) use raw HTTP against the
    ChatGPT backend and do not send SDK telemetry headers.
    """
    for key in list(request.headers.keys()):
        if key.lower().startswith("x-stainless-"):
            del request.headers[key]


@register(llm_param.LLMClientProtocol.CODEX_OAUTH)
class CodexClient(LLMClientABC):
    """LLM client for Codex API using ChatGPT subscription."""

    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        self._token_manager = CodexTokenManager()
        self._oauth = CodexOAuth(self._token_manager)

        if not self._token_manager.is_logged_in():
            raise CodexNotLoggedInError("Codex authentication required. Run 'klaude auth login codex' first.")

        self.client = self._create_client()

    def _create_client(self) -> AsyncOpenAI:
        """Create OpenAI client with Codex configuration."""
        state = self._token_manager.get_state()
        if state is None:
            raise CodexNotLoggedInError("Not logged in to Codex. Run 'klaude auth login codex' first.")

        http_client = create_async_http_client()
        http_client.event_hooks["request"].append(strip_stainless_headers)
        return AsyncOpenAI(
            api_key=state.access_token,
            base_url=CODEX_BASE_URL,
            timeout=create_http_timeout(),
            http_client=http_client,
            default_headers={
                **CODEX_HEADERS,
                "chatgpt-account-id": state.account_id,
            },
        )

    def _ensure_valid_token(self) -> None:
        """Ensure token is valid, refresh if needed."""
        state = self._token_manager.get_state()
        if state is None:
            raise CodexNotLoggedInError("Not logged in to Codex. Run 'klaude auth login codex' first.")

        if state.is_expired():
            self._oauth.refresh()
            # Recreate client with new token
            self.client = self._create_client()

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        # Ensure token is valid before API call
        self._ensure_valid_token()

        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        # Payload building re-encodes history images; keep it off the event loop.
        payload = await asyncio.to_thread(build_payload, param)
        extra_headers: dict[str, str] = {}
        affinity_id = cache_affinity_id(param)
        if affinity_id:
            # Session-affinity headers matching the pi Codex client to improve
            # ChatGPT backend prompt cache hit rate.
            extra_headers["session-id"] = affinity_id
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
            error_message = f"{e.__class__.__name__} {e!s}"
            return error_llm_stream(metadata_tracker, error=error_message)

        return ResponsesLLMStream(stream, param=param, metadata_tracker=metadata_tracker)
