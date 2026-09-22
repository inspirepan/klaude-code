from typing import Any, cast

from klaude_code.llm.openai_codex.client import build_payload as build_codex_payload
from klaude_code.protocol import llm_param


def _reasoning(model_id: str, effort: str) -> dict[str, Any]:
    param = llm_param.LLMCallParameter(
        input=[],
        model_id=model_id,
        thinking=llm_param.Thinking(reasoning_effort=cast(Any, effort)),
    )
    return cast(dict[str, Any], build_codex_payload(param)["reasoning"])


def test_gpt6_lifts_efforts_it_no_longer_accepts() -> None:
    # GPT-6 dropped none/minimal; sending either returns a 400 upstream.
    for model_id in ("gpt-6-astra", "gpt-6-sol", "gpt-6-luna"):
        assert _reasoning(model_id, "minimal")["effort"] == "low"
        assert _reasoning(model_id, "none")["effort"] == "low"


def test_gpt6_passes_supported_efforts_through() -> None:
    for model_id in ("gpt-6-astra", "gpt-6-sol", "gpt-6-luna"):
        for effort in ("low", "medium", "high", "xhigh", "max"):
            assert _reasoning(model_id, effort)["effort"] == effort


def test_gpt56_keeps_its_own_effort_range() -> None:
    assert _reasoning("gpt-5.6-sol", "minimal")["effort"] == "minimal"
    assert _reasoning("gpt-5.6-sol", "none")["effort"] == "none"
