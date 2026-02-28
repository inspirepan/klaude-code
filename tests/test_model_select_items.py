from __future__ import annotations

from types import SimpleNamespace

from klaude_code.protocol import llm_param
from klaude_code.tui.terminal.selector import SelectItem, build_model_select_items


def _title_text(item: SelectItem[str]) -> str:
    return "".join(text for _, text in item.title)


def test_build_model_select_items_hides_provider_on_each_model_row() -> None:
    models = [
        SimpleNamespace(
            model_name="kimi",
            model_id="kimi-k2.5-free",
            provider="opencode-zen",
            selector="kimi@opencode-zen",
            thinking=None,
            verbosity=None,
            provider_routing=None,
        ),
        SimpleNamespace(
            model_name="minimax",
            model_id="minimax-m2.5-free",
            provider="opencode-zen",
            selector="minimax@opencode-zen",
            thinking=llm_param.Thinking(budget_tokens=2048),
            verbosity=None,
            provider_routing=None,
        ),
    ]

    items = build_model_select_items(models)

    header_text = _title_text(items[0]).lower()
    kimi_text = _title_text(items[1])
    minimax_text = _title_text(items[2])

    assert "opencode-zen (2)" in header_text
    assert "→ kimi-k2.5-free" in kimi_text
    assert "→ minimax-m2.5-free" in minimax_text
    assert "opencode-zen" not in kimi_text
    assert "opencode-zen" not in minimax_text
    assert "thinking budget 2048" in minimax_text
