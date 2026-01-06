import asyncio
from typing import Any

import pytest
from google.genai import types

from klaude_code.llm.google.client import GoogleStreamStateManager, parse_google_stream
from klaude_code.llm.usage import MetadataTracker
from klaude_code.protocol import llm_param, message


def run(coro: Any):
    return asyncio.run(coro)


def _mk_chunk(
    *,
    response_id: str,
    image_bytes: bytes,
    finish_reason: types.FinishReason | None,
    thought: bool | None,
) -> types.GenerateContentResponse:
    part = types.Part(inline_data=types.Blob(data=image_bytes, mime_type="image/png"), thought=thought)
    content = types.Content(role="model", parts=[part])
    candidate = types.Candidate(content=content, index=0, finish_reason=finish_reason)
    return types.GenerateContentResponse(response_id=response_id, candidates=[candidate])


def test_google_skips_thought_images(monkeypatch: pytest.MonkeyPatch) -> None:
    saved_data_urls: list[str] = []

    def _fake_save_assistant_image(*, data_url: str, session_id: str | None, response_id: str | None, image_index: int):
        saved_data_urls.append(data_url)
        return message.ImageFilePart(
            file_path=f"/tmp/fake-img-{image_index}.png",
            mime_type="image/png",
            byte_size=123,
            sha256="deadbeef",
        )

    monkeypatch.setattr("klaude_code.llm.google.client.save_assistant_image", _fake_save_assistant_image)

    async def _collect() -> list[message.LLMStreamItem]:
        async def _stream():
            yield _mk_chunk(response_id="r1", image_bytes=b"img-1", finish_reason=None, thought=True)
            yield _mk_chunk(response_id="r1", image_bytes=b"img-2", finish_reason=types.FinishReason.STOP, thought=None)

        param = llm_param.LLMCallParameter(
            model_id="gemini-3-pro-image-preview",
            input=[message.UserMessage(parts=[message.TextPart(text="draw a cat")])],
            session_id="sid",
        )
        tracker = MetadataTracker(cost_config=None)
        state = GoogleStreamStateManager(param_model=str(param.model_id))
        return [
            item async for item in parse_google_stream(_stream(), param=param, metadata_tracker=tracker, state=state)
        ]

    items = run(_collect())

    image_deltas = [i for i in items if isinstance(i, message.AssistantImageDelta)]
    final_msgs = [i for i in items if isinstance(i, message.AssistantMessage)]

    assert len(image_deltas) == 1
    assert len(final_msgs) == 1
    assert len([p for p in final_msgs[0].parts if isinstance(p, message.ImageFilePart)]) == 1
    assert len(saved_data_urls) == 1
    assert "aW1nLTI" in saved_data_urls[0]  # base64("img-2")


def test_google_streams_multiple_response_images(monkeypatch: pytest.MonkeyPatch) -> None:
    saved_paths: list[str] = []

    def _fake_save_assistant_image(*, data_url: str, session_id: str | None, response_id: str | None, image_index: int):
        path = f"/tmp/fake-img-{image_index}.png"
        saved_paths.append(path)
        return message.ImageFilePart(
            file_path=path,
            mime_type="image/png",
            byte_size=123,
            sha256="deadbeef",
        )

    monkeypatch.setattr("klaude_code.llm.google.client.save_assistant_image", _fake_save_assistant_image)

    async def _collect() -> list[message.LLMStreamItem]:
        async def _stream():
            yield _mk_chunk(response_id="r2", image_bytes=b"img-1", finish_reason=None, thought=None)
            yield _mk_chunk(response_id="r2", image_bytes=b"img-2", finish_reason=types.FinishReason.STOP, thought=None)

        param = llm_param.LLMCallParameter(
            model_id="gemini-2.0-flash",
            input=[message.UserMessage(parts=[message.TextPart(text="draw a cat")])],
            session_id="sid",
        )
        tracker = MetadataTracker(cost_config=None)
        state = GoogleStreamStateManager(param_model=str(param.model_id))
        return [
            item async for item in parse_google_stream(_stream(), param=param, metadata_tracker=tracker, state=state)
        ]

    items = run(_collect())

    image_deltas = [i for i in items if isinstance(i, message.AssistantImageDelta)]
    final_msgs = [i for i in items if isinstance(i, message.AssistantMessage)]

    assert len(image_deltas) == 2
    assert len(final_msgs) == 1
    assert len([p for p in final_msgs[0].parts if isinstance(p, message.ImageFilePart)]) == 2
    assert saved_paths == ["/tmp/fake-img-0.png", "/tmp/fake-img-1.png"]
