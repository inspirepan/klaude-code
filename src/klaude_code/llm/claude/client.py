import json
from typing import override

import anthropic
import httpx
from anthropic import APIError

from klaude_code.auth.claude.exceptions import ClaudeNotLoggedInError
from klaude_code.auth.claude.oauth import ClaudeOAuth
from klaude_code.auth.claude.token_manager import ClaudeTokenManager
from klaude_code.const import (
    ANTHROPIC_BETA_FINE_GRAINED_TOOL_STREAMING,
    ANTHROPIC_BETA_INTERLEAVED_THINKING,
    ANTHROPIC_BETA_OAUTH,
    LLM_HTTP_TIMEOUT_CONNECT,
    LLM_HTTP_TIMEOUT_READ,
    LLM_HTTP_TIMEOUT_TOTAL,
)
from klaude_code.llm.anthropic.client import AnthropicLLMStream, build_payload
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param

_CLAUDE_OAUTH_REQUIRED_BETAS: tuple[str, ...] = (
    ANTHROPIC_BETA_OAUTH,
    ANTHROPIC_BETA_FINE_GRAINED_TOOL_STREAMING,
)


@register(llm_param.LLMClientProtocol.CLAUDE_OAUTH)
class ClaudeClient(LLMClientABC):
    """Claude OAuth client using Anthropic messages API with Bearer auth token."""

    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)

        if config.base_url:
            raise ValueError("CLAUDE protocol does not support custom base_url")

        self._token_manager = ClaudeTokenManager()
        self._oauth = ClaudeOAuth(self._token_manager)

        if not self._token_manager.is_logged_in():
            raise ClaudeNotLoggedInError("Claude authentication required. Run 'klaude login claude' first.")

        self.client = self._create_client()

    def _create_client(self) -> anthropic.AsyncAnthropic:
        token = self._oauth.ensure_valid_token()
        return anthropic.AsyncAnthropic(
            auth_token=token,
            timeout=httpx.Timeout(LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ),
        )

    def _ensure_valid_token(self) -> None:
        state = self._token_manager.get_state()
        if state is None:
            raise ClaudeNotLoggedInError("Not logged in to Claude. Run 'klaude login claude' first.")

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

        # Anthropic OAuth requires the oauth beta flag
        extra_betas = list(_CLAUDE_OAUTH_REQUIRED_BETAS)
        payload = build_payload(param, extra_betas=extra_betas)

        # Keep the interleaved-thinking beta in sync with configured thinking.
        if not (param.thinking and param.thinking.type == "enabled"):
            payload["betas"] = [b for b in payload.get("betas", []) if b != ANTHROPIC_BETA_INTERLEAVED_THINKING]

        log_debug(
            json.dumps(payload, ensure_ascii=False, default=str),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )

        try:
            stream = self.client.beta.messages.create(
                **payload,
                extra_headers={"extra": json.dumps({"session_id": param.session_id}, sort_keys=True)},
            )
            return AnthropicLLMStream(stream, param=param, metadata_tracker=metadata_tracker)
        except (APIError, httpx.HTTPError) as e:
            error_message = f"{e.__class__.__name__} {e!s}"
            return error_llm_stream(metadata_tracker, error=error_message)
