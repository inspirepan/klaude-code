import asyncio
import json
from threading import get_ident
from unittest.mock import AsyncMock, Mock

import httpx
import openai
import pytest

from klaude_code.const import ANTHROPIC_BETA_INTERLEAVED_THINKING
from klaude_code.llm.openai_compatible import client as compatible
from klaude_code.llm.openrouter import client as router
from klaude_code.protocol import llm_param, message


@pytest.mark.parametrize("session_id", ["test-session", None])
@pytest.mark.parametrize("provider", ["compatible", "azure", "router-claude", "router-gemini4"])
def test_chat_completions_wire_behavior(monkeypatch: pytest.MonkeyPatch, provider: str, session_id: str | None) -> None:
    is_router = provider.startswith("router")
    model_id = "google/gemini-4-argon" if provider == "router-gemini4" else "anthropic/claude-sonnet-4.6"
    requests: list[httpx.Request] = []
    main_thread = get_ident()
    module = router if is_router else compatible
    build_payload = module.build_payload

    def build_off_thread(param: llm_param.LLMCallParameter) -> object:
        assert get_ident() != main_thread
        return build_payload(param)

    monkeypatch.setattr(module, "build_payload", build_off_thread)

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content='data: {"id":"response-id","model":"upstream-model","provider":"upstream",'
            '"choices":[{"index":0,"delta":{"reasoning_content":"thought","content":"OK"},'
            '"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}'
            "\n\ndata: [DONE]\n\n",
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
            monkeypatch.setattr(module, "create_async_http_client", lambda: http_client)
            config = llm_param.LLMConfigParameter(
                protocol=llm_param.LLMClientProtocol.OPENROUTER if is_router else llm_param.LLMClientProtocol.OPENAI,
                provider_name="opencode-go",
                model_id=model_id,
                api_key="test-key",
                is_azure=provider == "azure",
                base_url="https://example.openai.azure.com" if provider == "azure" else None,
                azure_api_version="2024-10-01",
                max_tokens=1024,
                cost=llm_param.Cost(input=1, output=2),
            )
            client = router.OpenRouterClient(config) if is_router else compatible.OpenAICompatibleClient(config)
            try:
                stream = await client.call(
                    llm_param.LLMCallParameter(
                        input=[message.UserMessage(parts=[message.TextPart(text="hi")])], session_id=session_id
                    )
                )
                items = [item async for item in stream]
                final = items[-1]
                assert isinstance(final, message.AssistantMessage)
                assert final.stop_reason == "stop"
                assert final.response_id == "response-id"
                assert [part.text for part in final.parts if isinstance(part, message.TextPart)] == ["OK"]
                assert [part.text for part in final.parts if isinstance(part, message.ThinkingTextPart)] == (
                    [] if is_router else ["thought"]
                )
                assert final.usage is not None
                assert final.usage.provider == ("openrouter/upstream" if is_router else "upstream")
                assert final.usage.model_name == "upstream-model"
                assert final.usage.input_tokens == 10
                assert final.usage.output_tokens == 2
                assert final.usage.input_cost == pytest.approx(0.00001)
                assert final.usage.output_cost == pytest.approx(0.000004)
                assert stream.get_partial_message() is None
            finally:
                await client.client.close()

    asyncio.run(run())
    assert len(requests) == 1
    request = requests[0]
    body = json.loads(request.content)
    assert body["model"] == model_id
    assert body["max_tokens"] == 1024
    assert request.headers["User-Agent"] == "klaude-code/2"
    assert request.headers.get("x-session-id") == session_id
    if is_router:
        assert "x-opencode-session" not in request.headers
        assert body["usage"] == {"include": True}
        assert body["reasoning"] == ({"effort": "medium"} if provider == "router-gemini4" else {"enabled": False})
    else:
        assert request.headers["x-opencode-session"]
        assert "usage" not in body
        assert "reasoning" not in body
    assert request.headers.get("x-anthropic-beta") == (
        ANTHROPIC_BETA_INTERLEAVED_THINKING if provider == "router-claude" else None
    )
    assert request.extensions["timeout"]["read"] == (1200.0 if provider == "router-gemini4" else 285.0)
    if provider == "azure":
        assert request.url.path == f"/openai/deployments/{model_id}/chat/completions"
        assert request.url.params["api-version"] == "2024-10-01"


@pytest.mark.parametrize("is_router", [False, True])
@pytest.mark.parametrize(
    ("stage", "error"),
    [
        ("payload", ValueError("invalid payload")),
        ("payload", OSError("image read failed")),
        ("payload", TypeError("unexpected failure")),
        (
            "request",
            openai.BadRequestError(
                "bad request", response=httpx.Response(400, request=httpx.Request("POST", "https://test")), body=None
            ),
        ),
        ("request", httpx.RemoteProtocolError("connection closed")),
        ("request", RuntimeError("unexpected failure")),
    ],
    ids=[
        "invalid-payload",
        "image-error",
        "unexpected-payload-error",
        "sdk-error",
        "http-error",
        "unexpected-request-error",
    ],
)
def test_chat_completions_request_error_boundary(
    monkeypatch: pytest.MonkeyPatch, is_router: bool, stage: str, error: Exception
) -> None:
    async def run() -> None:
        config = llm_param.LLMConfigParameter(
            protocol=llm_param.LLMClientProtocol.OPENROUTER if is_router else llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_id="test-model",
        )
        client = router.OpenRouterClient(config) if is_router else compatible.OpenAICompatibleClient(config)
        create = AsyncMock(side_effect=error)
        monkeypatch.setattr(client.client.chat.completions, "create", create)
        if stage == "payload":
            monkeypatch.setattr(router if is_router else compatible, "build_payload", Mock(side_effect=error))
        try:
            param = llm_param.LLMCallParameter(input=[])
            if isinstance(error, (RuntimeError, TypeError)):
                with pytest.raises(type(error), match="unexpected failure"):
                    await client.call(param)
                return
            stream = await client.call(param)
            items = [item async for item in stream]
            assert len(items) == 2
            assert isinstance(items[0], message.StreamErrorItem)
            assert items[0].error.startswith(type(error).__name__)
            assert isinstance(items[1], message.AssistantMessage)
            assert items[1].stop_reason == "error"
            assert items[1].parts == []
            assert items[1].usage is not None
            assert stream.get_partial_message() is None
        finally:
            if stage == "payload":
                create.assert_not_called()
            await client.client.close()

    asyncio.run(run())
