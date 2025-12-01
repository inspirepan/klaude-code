"""Codex LLM client using ChatGPT subscription via OAuth."""

import time
from collections.abc import AsyncGenerator
from typing import override

import httpx
from openai import AsyncOpenAI

from klaude_code.auth.codex.exceptions import CodexNotLoggedInError
from klaude_code.auth.codex.oauth import CodexOAuth
from klaude_code.auth.codex.token_manager import CodexTokenManager
from klaude_code.llm.client import LLMClientABC, call_with_logged_payload
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.llm.responses.client import parse_responses_stream
from klaude_code.llm.responses.input import convert_history_to_input, convert_tool_schema
from klaude_code.protocol import llm_param, model

# Codex API configuration
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_HEADERS = {
    "originator": "codex_cli_rs",
    # Mocked Codex-style user agent string
    "User-Agent": "codex_cli_rs/0.0.0-klaude",
}


@register(llm_param.LLMClientProtocol.CODEX)
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
            timeout=httpx.Timeout(300.0, connect=15.0, read=285.0),
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
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem, None]:
        # Ensure token is valid before API call
        self._ensure_valid_token()

        param = apply_config_defaults(param, self.get_llm_config())

        # Codex API requires store=False
        param.store = False

        request_start_time = time.time()

        inputs = convert_history_to_input(param.input, param.model)
        tools = convert_tool_schema(param.tools)

        session_id = param.session_id or ""
        # Must send conversation_id/session_id headers to improve ChatGPT backend prompt cache hit rate.
        extra_headers: dict[str, str] = {}
        if session_id:
            extra_headers["conversation_id"] = session_id
            extra_headers["session_id"] = session_id

        stream = await call_with_logged_payload(
            self.client.responses.create,
            model=str(param.model),
            tool_choice="auto",
            parallel_tool_calls=True,
            include=[
                "reasoning.encrypted_content",
            ],
            store=False,  # Always False for Codex
            stream=True,
            input=inputs,
            instructions=param.system,
            tools=tools,
            text={
                "verbosity": param.verbosity,
            },
            prompt_cache_key=session_id,
            reasoning={
                "effort": param.thinking.reasoning_effort,
                "summary": param.thinking.reasoning_summary,
            }
            if param.thinking and param.thinking.reasoning_effort
            else None,
            extra_headers=extra_headers,
        )

        async for item in parse_responses_stream(stream, param, self._config.cost, request_start_time):
            yield item
