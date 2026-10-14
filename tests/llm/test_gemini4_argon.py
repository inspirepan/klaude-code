import asyncio
import json

import httpx
import pytest
from google.oauth2.credentials import Credentials

from klaude_code.llm.google.client import GoogleClient
from klaude_code.llm.google_vertex.client import GoogleVertexClient
from klaude_code.llm.openrouter.client import build_payload
from klaude_code.protocol import llm_param, message


@pytest.mark.parametrize("vertex", [False, True])
@pytest.mark.parametrize(
    ("thinking", "level"),
    [
        (None, "MEDIUM"),
        (llm_param.Thinking(reasoning_effort="low"), "LOW"),
        (llm_param.Thinking(reasoning_effort="medium"), "MEDIUM"),
        (llm_param.Thinking(reasoning_effort="high"), "HIGH"),
        (llm_param.Thinking(reasoning_effort="minimal", budget_tokens=1024), "LOW"),
        (llm_param.Thinking(reasoning_effort="none", budget_tokens=0), "LOW"),
        (llm_param.Thinking(type="disabled"), "LOW"),
        (llm_param.Thinking(budget_tokens=1024), "MEDIUM"),
        (llm_param.Thinking(reasoning_effort="xhigh"), "HIGH"),
        (llm_param.Thinking(reasoning_effort="max"), "HIGH"),
    ],
)
def test_argon_google_wire_payload(
    monkeypatch: pytest.MonkeyPatch, vertex: bool, thinking: llm_param.Thinking | None, level: str
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content='data: {"candidates":[{"content":{"role":"model","parts":[{"text":"ok"}]},'
            '"finishReason":"STOP"}]}\n\n',
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
            monkeypatch.setattr("klaude_code.llm.google.client.create_async_http_client", lambda: http_client)
            monkeypatch.setattr(
                "klaude_code.llm.google_vertex.client.load_credentials_from_file",
                lambda *args, **kwargs: (Credentials(token="test-token"), None),
            )
            config = llm_param.LLMConfigParameter(
                protocol=llm_param.LLMClientProtocol.GOOGLE_VERTEX if vertex else llm_param.LLMClientProtocol.GOOGLE,
                model_id="gemini-4-argon",
                api_key=None if vertex else "test-key",
                google_application_credentials="fake.json" if vertex else None,
                google_cloud_project="test-project" if vertex else None,
                google_cloud_location="global" if vertex else None,
                max_tokens=65536,
                temperature=0.2,
                thinking=thinking,
            )
            client = GoogleVertexClient(config) if vertex else GoogleClient(config)
            stream = await client.call(
                llm_param.LLMCallParameter(
                    input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
                    session_id="test-session",
                )
            )
            items = [item async for item in stream]
            assert isinstance(items[-1], message.AssistantMessage)
            assert items[-1].stop_reason == "stop"
            await client.client.aio.aclose()

    asyncio.run(run())
    assert len(requests) == 1
    request = requests[0]
    assert "gemini-4-argon:streamGenerateContent" in str(request.url)
    body = json.loads(request.content)
    assert body["generationConfig"] == {
        "maxOutputTokens": 65536,
        "thinkingConfig": {"include_thoughts": True, "thinking_level": level},
    }
    assert "cachedContent" not in body
    assert request.headers["x-session-id"] == "test-session"
    assert request.extensions["timeout"]["read"] == 1200.0


@pytest.mark.parametrize(
    ("thinking", "effort"),
    [
        (None, "medium"),
        (llm_param.Thinking(reasoning_effort="low"), "low"),
        (llm_param.Thinking(reasoning_effort="medium"), "medium"),
        (llm_param.Thinking(reasoning_effort="high"), "high"),
        (llm_param.Thinking(reasoning_effort="minimal", budget_tokens=1024), "low"),
        (llm_param.Thinking(reasoning_effort="none"), "low"),
        (llm_param.Thinking(type="disabled"), "low"),
        (llm_param.Thinking(budget_tokens=1024), "medium"),
    ],
)
def test_argon_openrouter_payload(thinking: llm_param.Thinking | None, effort: str) -> None:
    payload, extra_body, _ = build_payload(
        llm_param.LLMCallParameter(
            model_id="google/gemini-4-argon",
            input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
            thinking=thinking,
            temperature=0.2,
            max_tokens=65536,
        )
    )
    assert payload["model"] == "google/gemini-4-argon"
    assert payload["max_tokens"] == 65536
    assert extra_body["reasoning"] == {"effort": effort}
    assert not {"temperature", "top_p", "top_k"}.intersection(payload)
    assert not {"temperature", "top_p", "top_k"}.intersection(extra_body)
