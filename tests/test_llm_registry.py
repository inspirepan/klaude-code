import importlib

import pytest

from klaude_code.llm import registry
from klaude_code.protocol import llm_param


def test_load_protocol_marks_loaded_after_import(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: set[llm_param.LLMClientProtocol] = set()
    calls: list[str] = []

    def _fake_import(module_path: str) -> None:
        calls.append(module_path)

    monkeypatch.setattr(registry, "_loaded_protocols", loaded)
    monkeypatch.setattr(
        registry,
        "_PROTOCOL_MODULES",
        {llm_param.LLMClientProtocol.OPENAI: "fake.module"},
    )
    monkeypatch.setattr(importlib, "import_module", _fake_import)

    registry.load_protocol(llm_param.LLMClientProtocol.OPENAI)

    assert calls == ["fake.module"]
    assert llm_param.LLMClientProtocol.OPENAI in loaded


def test_load_protocol_unknown_does_not_mark_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: set[llm_param.LLMClientProtocol] = set()
    monkeypatch.setattr(registry, "_loaded_protocols", loaded)
    monkeypatch.setattr(registry, "_PROTOCOL_MODULES", {})

    with pytest.raises(ValueError):
        registry.load_protocol(llm_param.LLMClientProtocol.OPENAI)

    assert llm_param.LLMClientProtocol.OPENAI not in loaded


def test_load_protocol_skips_import_when_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = {llm_param.LLMClientProtocol.OPENAI}
    monkeypatch.setattr(registry, "_loaded_protocols", loaded)
    monkeypatch.setattr(
        registry,
        "_PROTOCOL_MODULES",
        {llm_param.LLMClientProtocol.OPENAI: "fake.module"},
    )

    def _raise_import(_: str) -> None:
        raise AssertionError("import should not be called")

    monkeypatch.setattr(importlib, "import_module", _raise_import)

    registry.load_protocol(llm_param.LLMClientProtocol.OPENAI)
