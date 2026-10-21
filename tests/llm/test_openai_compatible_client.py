import asyncio

import httpx
import pytest

from klaude_code.llm.openai_compatible.client import OpenAICompatibleClient
from klaude_code.protocol import llm_param, message


@pytest.mark.parametrize("provider_name", ["opencode-go", "other-provider"])
@pytest.mark.parametrize("session_id", ["test-session", None])
def test_session_headers(monkeypatch: pytest.MonkeyPatch, provider_name: str, session_id: str | None) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content='data: {"id":"test","choices":[{"index":0,"delta":{"content":"OK"},'
            '"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
            monkeypatch.setattr(
                "klaude_code.llm.openai_compatible.client.create_async_http_client", lambda: http_client
            )
            client = OpenAICompatibleClient(
                llm_param.LLMConfigParameter(
                    provider_name=provider_name,
                    protocol=llm_param.LLMClientProtocol.OPENAI,
                    model_id="deepseek-flash",
                    api_key="test-key",
                )
            )
            try:
                stream = await client.call(
                    llm_param.LLMCallParameter(
                        input=[message.UserMessage(parts=[message.TextPart(text="hi")])], session_id=session_id
                    )
                )
                items = [item async for item in stream]
                assert isinstance(items[-1], message.AssistantMessage)
                assert items[-1].stop_reason == "stop"
            finally:
                await client.client.close()

    asyncio.run(run())
    assert len(requests) == 1
    headers = requests[0].headers
    assert headers.get("x-session-id") == session_id
    assert headers.get("x-opencode-session") == (session_id if provider_name == "opencode-go" else None)
