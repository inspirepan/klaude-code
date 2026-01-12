"""Codex LLM client using ChatGPT subscription via OAuth."""

import json
from typing import override

import httpx
import openai
from openai import AsyncOpenAI
from openai.types.responses.response_create_params import ResponseCreateParamsStreaming

from klaude_code.auth.codex.exceptions import CodexNotLoggedInError
from klaude_code.auth.codex.oauth import CodexOAuth
from klaude_code.auth.codex.token_manager import CodexTokenManager
from klaude_code.const import (
    CODEX_BASE_URL,
    CODEX_USER_AGENT,
    LLM_HTTP_TIMEOUT_CONNECT,
    LLM_HTTP_TIMEOUT_READ,
    LLM_HTTP_TIMEOUT_TOTAL,
)
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.openai_responses.client import ResponsesLLMStream
from klaude_code.llm.openai_responses.input import convert_history_to_input, convert_tool_schema
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param


def build_payload(param: llm_param.LLMCallParameter) -> ResponseCreateParamsStreaming:
    """Build Codex API request parameters."""
    inputs = convert_history_to_input(param.input, param.model_id)
    tools = convert_tool_schema(param.tools)

    session_id = param.session_id or ""

    payload: ResponseCreateParamsStreaming = {
        "model": str(param.model_id),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "include": [
            "reasoning.encrypted_content",
        ],
        "store": False,
        "stream": True,
        "input": inputs,
        "instructions": param.system,
        "tools": tools,
        "prompt_cache_key": session_id,
        # max_output_token and temperature is not supported in Codex API
    }

    if param.thinking and param.thinking.reasoning_effort:
        payload["reasoning"] = {
            "effort": param.thinking.reasoning_effort,
            "summary": param.thinking.reasoning_summary,
        }

    if param.verbosity:
        payload["text"] = {"verbosity": param.verbosity}

    return payload


CODEX_HEADERS = {
    "originator": "codex_cli_rs",
    "User-Agent": CODEX_USER_AGENT,
    "OpenAI-Beta": "responses=experimental",
}


@register(llm_param.LLMClientProtocol.CODEX_OAUTH)
class CodexClient(LLMClientABC):
    """LLM client for Codex API using ChatGPT subscription."""

    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        self._token_manager = CodexTokenManager()
        self._oauth = CodexOAuth(self._token_manager)

        if not self._token_manager.is_logged_in():
            raise CodexNotLoggedInError("Codex authentication required. Run 'klaude login codex' first.")

        self.client = self._create_client()

    def _create_client(self) -> AsyncOpenAI:
        """Create OpenAI client with Codex configuration."""
        state = self._token_manager.get_state()
        if state is None:
            raise CodexNotLoggedInError("Not logged in to Codex. Run 'klaude login codex' first.")

        return AsyncOpenAI(
            api_key=state.access_token,
            base_url=CODEX_BASE_URL,
            timeout=httpx.Timeout(LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ),
            default_headers={
                **CODEX_HEADERS,
                "chatgpt-account-id": state.account_id,
            },
        )

    def _ensure_valid_token(self) -> None:
        """Ensure token is valid, refresh if needed."""
        state = self._token_manager.get_state()
        if state is None:
            raise CodexNotLoggedInError("Not logged in to Codex. Run 'klaude login codex' first.")

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

        payload = build_payload(param)

        session_id = param.session_id or ""
        extra_headers: dict[str, str] = {}
        if session_id:
            # Must send conversation_id/session_id headers to improve ChatGPT backend prompt cache hit rate.
            extra_headers["conversation_id"] = session_id
            extra_headers["session_id"] = session_id

        log_debug(
            json.dumps(payload, ensure_ascii=False, default=str),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )
        try:
            stream = await self.client.responses.create(
                **payload,
                extra_headers=extra_headers,
            )
        except (openai.OpenAIError, httpx.HTTPError) as e:
            error_message = f"{e.__class__.__name__} {e!s}"

            # Check for invalid instruction error and invalidate prompt cache
            if _is_invalid_instruction_error(e) and param.model_id:
                _invalidate_prompt_cache_for_model(param.model_id)

            return error_llm_stream(metadata_tracker, error=error_message)

        return ResponsesLLMStream(stream, param=param, metadata_tracker=metadata_tracker)


def _is_invalid_instruction_error(e: Exception) -> bool:
    """Check if the error is related to invalid instructions."""
    error_str = str(e).lower()
    return "invalid instruction" in error_str or "invalid_instruction" in error_str


def _invalidate_prompt_cache_for_model(model_id: str) -> None:
    """Invalidate the cached prompt for a model to force refresh."""
    from klaude_code.llm.openai_codex.prompt_sync import invalidate_cache

    log_debug(
        f"Invalidating prompt cache for model {model_id} due to invalid instruction error",
        debug_type=DebugType.GENERAL,
    )
    invalidate_cache(model_id)
