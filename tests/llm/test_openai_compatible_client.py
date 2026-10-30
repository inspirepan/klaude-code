import asyncio
from uuid import UUID

import httpx
import pytest

from klaude_code.llm.openai_compatible.client import OpenAICompatibleClient
from klaude_code.llm.openai_responses.client import ResponsesClient
from klaude_code.protocol import llm_param, message


@pytest.mark.parametrize(
    ("client_class", "protocol", "provider_name", "client_module"),
    [
        (OpenAICompatibleClient, llm_param.LLMClientProtocol.OPENAI, "opencode-go", "openai_compatible"),
        (ResponsesClient, llm_param.LLMClientProtocol.RESPONSES, "opencode-go-responses", "openai_responses"),
        (OpenAICompatibleClient, llm_param.LLMClientProtocol.OPENAI, "other-provider", "openai_compatible"),
        (ResponsesClient, llm_param.LLMClientProtocol.RESPONSES, "other-provider", "openai_responses"),
    ],
)
@pytest.mark.parametrize("session_id", ["test-session", None, ""])
def test_session_headers(
    monkeypatch: pytest.MonkeyPatch,
    client_class: type[OpenAICompatibleClient] | type[ResponsesClient],
    protocol: llm_param.LLMClientProtocol,
    provider_name: str,
    client_module: str,
    session_id: str | None,
) -> None:
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
            monkeypatch.setattr(f"klaude_code.llm.{client_module}.client.create_async_http_client", lambda: http_client)
            client = client_class(
                llm_param.LLMConfigParameter(
                    provider_name=provider_name,
                    protocol=protocol,
                    model_id="deepseek-flash",
                    api_key="test-key",
                )
            )
            try:
                param = llm_param.LLMCallParameter(
                    input=[message.UserMessage(parts=[message.TextPart(text="hi")])], session_id=session_id
                )
                for _ in range(2):
                    stream = await client.call(param)
                    if protocol == llm_param.LLMClientProtocol.OPENAI:
                        items = [item async for item in stream]
                        assert isinstance(items[-1], message.AssistantMessage)
                        assert items[-1].stop_reason == "stop"
                assert param.session_id == session_id
            finally:
                await client.client.close()

    asyncio.run(run())
    assert len(requests) == 2
    for request in requests:
        assert request.headers.get("x-session-id") == (session_id or None)
        opencode_session = request.headers.get("x-opencode-session")
        if provider_name == "other-provider":
            assert opencode_session is None
        elif session_id:
            assert opencode_session == session_id
        else:
            assert opencode_session is not None
            assert UUID(opencode_session).version == 4
    if provider_name != "other-provider" and not session_id:
        assert requests[0].headers["x-opencode-session"] != requests[1].headers["x-opencode-session"]
