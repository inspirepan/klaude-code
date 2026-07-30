"""xAI Responses API client using Grok Build OAuth."""

from typing import override

from openai import AsyncOpenAI
from openai.types.responses.response_create_params import ResponseCreateParamsBase

from klaude_code.auth.xai.exceptions import XaiNotLoggedInError
from klaude_code.auth.xai.oauth import XaiOAuth
from klaude_code.auth.xai.token_manager import XaiTokenManager
from klaude_code.llm.client import LLMStreamABC
from klaude_code.llm.http import create_http_timeout
from klaude_code.llm.openai_responses.client import ResponsesClient
from klaude_code.llm.registry import register
from klaude_code.protocol import llm_param

XAI_BASE_URL = "https://api.x.ai/v1"
XAI_USER_AGENT = "klaude-code/2"
GROK_BUILD_MODEL_ID = "grok-build-0.1"


@register(llm_param.LLMClientProtocol.XAI_OAUTH)
class XaiOAuthClient(ResponsesClient):
    """Responses API client for xAI OAuth subscriptions."""

    def __init__(self, config: llm_param.LLMConfigParameter):
        self._token_manager = XaiTokenManager()
        self._oauth = XaiOAuth(self._token_manager)
        if not self._token_manager.is_logged_in():
            raise XaiNotLoggedInError("xAI authentication required. Run 'klaude auth login xai' first.")
        super().__init__(config)

    def _create_client(self, config: llm_param.LLMConfigParameter) -> AsyncOpenAI:
        """Create an API client from the stored OAuth token."""
        if config.base_url and config.base_url.rstrip("/") != XAI_BASE_URL:
            raise ValueError("xAI OAuth only supports the official https://api.x.ai/v1 endpoint")
        state = self._token_manager.get_state()
        if state is None:
            raise XaiNotLoggedInError("Not logged in to xAI. Run 'klaude auth login xai' first.")
        return AsyncOpenAI(
            api_key=state.access_token,
            base_url=XAI_BASE_URL,
            default_headers={"User-Agent": XAI_USER_AGENT},
            timeout=create_http_timeout(),
        )

    def _ensure_valid_token(self) -> None:
        """Refresh an expired OAuth token before making an API request."""
        state = self._token_manager.get_state()
        if state is None:
            raise XaiNotLoggedInError("Not logged in to xAI. Run 'klaude auth login xai' first.")
        if state.is_expired():
            self._oauth.refresh()
            self.client = self._create_client(self._config)

    def _build_payload(self, param: llm_param.LLMCallParameter) -> ResponseCreateParamsBase:
        payload = super()._build_payload(param)
        if param.model_id == GROK_BUILD_MODEL_ID:
            # Grok Build reasons by default but rejects explicit reasoning controls.
            payload.pop("reasoning", None)
            payload.pop("include", None)
        return payload

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "XaiOAuthClient":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self._ensure_valid_token()
        return await super().call(param)
