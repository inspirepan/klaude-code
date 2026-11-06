import asyncio
import threading
from types import SimpleNamespace

import pytest

from klaude_code.auth.base import BaseAuthState
from klaude_code.llm.chatgpt import client as chatgpt_client
from klaude_code.llm.xai_oauth import client as xai_client
from klaude_code.protocol import llm_param


@pytest.mark.parametrize("provider", ["chatgpt", "xai"])
def test_oauth_refresh_keeps_event_loop_responsive(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    state = BaseAuthState(access_token="expired", refresh_token="fake-refresh", expires_at=0)
    manager = SimpleNamespace(is_logged_in=lambda: True, get_state=lambda: state)
    requested_tokens: list[str] = []
    refresh_released = threading.Event()
    rebuild_started = threading.Event()
    rebuild_released = threading.Event()
    progressed_during_refresh: list[bool] = []

    def create_client(*, api_key: str, **_kwargs: object) -> SimpleNamespace:
        if api_key == "refreshed":
            rebuild_started.set()
            assert rebuild_released.wait(timeout=3.0)

        async def create_response(**_kwargs: object) -> object:
            requested_tokens.append(api_key)
            return object()

        return SimpleNamespace(responses=SimpleNamespace(create=create_response))

    if provider == "chatgpt":
        monkeypatch.setattr(chatgpt_client, "ChatGPTTokenManager", lambda: manager)
        monkeypatch.setattr(chatgpt_client, "AsyncOpenAI", create_client)
        monkeypatch.setattr(chatgpt_client, "create_async_http_client", lambda: None)
        client = chatgpt_client.ChatGPTClient(
            llm_param.LLMConfigParameter(protocol=llm_param.LLMClientProtocol.CHATGPT_OAUTH, model_id="gpt-5.4")
        )
    else:
        monkeypatch.setattr(xai_client, "XaiTokenManager", lambda: manager)
        monkeypatch.setattr(xai_client, "AsyncOpenAI", create_client)
        monkeypatch.setattr(xai_client, "create_async_http_client", lambda: None)
        client = xai_client.XaiOAuthClient(
            llm_param.LLMConfigParameter(protocol=llm_param.LLMClientProtocol.XAI_OAUTH, model_id="grok-build-0.1")
        )

    async def run() -> None:
        loop = asyncio.get_running_loop()
        refresh_started = asyncio.Event()

        def refresh() -> None:
            loop.call_soon_threadsafe(refresh_started.set)
            # Only the event loop can release this simulated lock/network wait.
            progressed_during_refresh.append(refresh_released.wait(timeout=1.0))
            state.access_token = "refreshed"
            state.expires_at = 4102444800

        monkeypatch.setattr(client._oauth, "refresh", refresh)
        param = llm_param.LLMCallParameter(input=[])
        requests = [asyncio.create_task(client.call(param))]
        try:
            await asyncio.wait_for(refresh_started.wait(), timeout=3.0)
            assert progressed_during_refresh == [], "OAuth refresh blocked the event loop"
            assert requested_tokens == []
            refresh_released.set()
            assert await asyncio.to_thread(rebuild_started.wait, 1.0)

            # The token is fresh, but the shared SDK client still has the old token.
            second_request = asyncio.create_task(client.call(param))
            requests.append(second_request)
            completed, _ = await asyncio.wait([second_request], timeout=0.1)
            assert not completed, "Concurrent request bypassed client renewal"
            assert requested_tokens == []
        finally:
            refresh_released.set()
            rebuild_released.set()
            await asyncio.gather(*requests)

        assert progressed_during_refresh == [True], "OAuth refresh blocked the event loop"
        assert requested_tokens == ["refreshed", "refreshed"]

    asyncio.run(run())
