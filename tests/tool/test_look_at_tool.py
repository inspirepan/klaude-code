from __future__ import annotations

import asyncio
import io
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from klaude_code.config.config import ModelConfigCandidate
from klaude_code.protocol import llm_param, message
from klaude_code.tool.core.context import TodoContext, ToolContext
from klaude_code.tool.file.look_at_tool import LookAtTool


def _tool_context(work_dir: Path) -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test-look-at", work_dir=work_dir)


def _write_png(path: Path, size: tuple[int, int] = (64, 48)) -> None:
    from PIL import Image

    image = Image.new("RGB", size, color=(200, 30, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


def _candidate(*, supports_vision: bool = True) -> ModelConfigCandidate:
    return ModelConfigCandidate(
        selector="fake-fast@fake-provider",
        model_name="fake-fast",
        provider="fake-provider",
        llm_config=llm_param.LLMConfigParameter(
            protocol=llm_param.LLMClientProtocol.ANTHROPIC,
            model_id="fake-fast",
            supports_vision=supports_vision,
        ),
    )


class _FakeConfig:
    def __init__(self, candidates: list[ModelConfigCandidate]) -> None:
        self.fast_model = ["fake-fast"]
        self._candidates = candidates

    def iter_model_config_candidates(self, model_preference: Any) -> list[ModelConfigCandidate]:
        del model_preference
        return self._candidates


class _FakeClient:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.call_params: list[llm_param.LLMCallParameter] = []

    async def call(self, param: llm_param.LLMCallParameter) -> AsyncIterator[Any]:
        self.call_params.append(param)

        async def _stream() -> AsyncIterator[Any]:
            yield message.AssistantTextDelta(content=self.answer)
            yield message.AssistantMessage(parts=[message.TextPart(text=self.answer)])

        return _stream()


def _patch_tool(
    monkeypatch: pytest.MonkeyPatch,
    *,
    candidates: list[ModelConfigCandidate],
    answer: str = "a red rectangle",
) -> _FakeClient:
    fake_client = _FakeClient(answer)
    monkeypatch.setattr("klaude_code.tool.file.look_at_tool.load_config", lambda: _FakeConfig(candidates))
    monkeypatch.setattr("klaude_code.tool.file.look_at_tool.create_llm_client", lambda config: fake_client)
    return fake_client


def _call(args: dict[str, Any], work_dir: Path) -> message.ToolResultMessage:
    return asyncio.run(LookAtTool.call(json.dumps(args), _tool_context(work_dir)))


def test_look_at_returns_vision_model_answer(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    fake_client = _patch_tool(monkeypatch, candidates=[_candidate()])
    image_path = tmp_path / "shot.png"
    _write_png(image_path)

    result = _call({"file_path": str(image_path), "question": "what color?"}, tmp_path)

    assert result.status == "success"
    assert result.output_text == "a red rectangle"
    assert len(fake_client.call_params) == 1
    param = fake_client.call_params[0]
    user_message = param.input[0]
    assert isinstance(user_message, message.UserMessage)
    assert isinstance(user_message.parts[0], message.TextPart)
    assert "what color?" in user_message.parts[0].text
    assert isinstance(user_message.parts[1], message.ImageFilePart)


def test_look_at_region_crops_before_sending(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    fake_client = _patch_tool(monkeypatch, candidates=[_candidate()])
    image_path = tmp_path / "shot.png"
    _write_png(image_path, size=(100, 50))

    result = _call({"file_path": str(image_path), "question": "zoom", "region": [10, 10, 30, 40]}, tmp_path)

    assert result.status == "success"
    assert result.output_text.startswith("[region 10,10,30,40 of 100x50]")
    sent_part = fake_client.call_params[0].input[0].parts[1]
    assert isinstance(sent_part, message.ImageFilePart)
    from PIL import Image

    with Image.open(sent_part.file_path) as sent_image:
        assert sent_image.size == (20, 30)


def test_look_at_empty_region_after_clamp_errors(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    _patch_tool(monkeypatch, candidates=[_candidate()])
    image_path = tmp_path / "shot.png"
    _write_png(image_path)

    result = _call({"file_path": str(image_path), "question": "q", "region": [0, 0, 0, 0]}, tmp_path)

    assert result.status == "error"
    assert "empty" in result.output_text


def test_look_at_missing_file_errors(isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del isolated_home
    _patch_tool(monkeypatch, candidates=[_candidate()])

    result = _call({"file_path": str(tmp_path / "nope.png"), "question": "q"}, tmp_path)

    assert result.status == "error"
    assert "does not exist" in result.output_text


def test_look_at_rejects_non_image_files(isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del isolated_home
    _patch_tool(monkeypatch, candidates=[_candidate()])
    text_path = tmp_path / "notes.txt"
    text_path.write_text("hello")

    result = _call({"file_path": str(text_path), "question": "q"}, tmp_path)

    assert result.status == "error"
    assert "Unsupported image file extension" in result.output_text


def test_look_at_errors_when_no_vision_fast_model(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    _patch_tool(monkeypatch, candidates=[_candidate(supports_vision=False)])
    image_path = tmp_path / "shot.png"
    _write_png(image_path)

    result = _call({"file_path": str(image_path), "question": "q"}, tmp_path)

    assert result.status == "error"
    assert "fast_model" in result.output_text
