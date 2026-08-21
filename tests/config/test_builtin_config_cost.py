from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from klaude_code.config.builtin_config import get_builtin_config
from klaude_code.config.config import ModelConfig

BEIJING = ZoneInfo("Asia/Shanghai")

# DeepSeek V4 off-peak prices, CNY per million tokens (effective 2026-08-17).
_EXPECTED_OFF_PEAK = {
    "deepseek-v4-flash": (1.5, 4.5, 0.05),
    "deepseek-v4-flash-vision-exp": (1.5, 4.5, 0.05),
    "deepseek-v4-pro": (4.5, 13.5, 0.15),
}


def _deepseek_models() -> list[ModelConfig]:
    config = get_builtin_config()
    providers = [p for p in config.provider_list or [] if p.provider_name == "deepseek"]
    assert providers, "builtin config lost the deepseek provider"
    return list(providers[0].model_list)


def test_deepseek_models_price_peak_at_double_off_peak() -> None:
    models = _deepseek_models()
    assert models

    for model in models:
        cost = model.cost
        assert cost is not None, f"{model.model_name} has no cost config"
        assert cost.currency == "CNY"

        expected = _EXPECTED_OFF_PEAK[model.model_id or ""]
        off_peak = cost.at(datetime(2026, 8, 17, 20, 0, tzinfo=BEIJING))
        assert (off_peak.input, off_peak.output, off_peak.cache_read) == expected

        peak = cost.at(datetime(2026, 8, 17, 10, 0, tzinfo=BEIJING))
        assert peak.input == pytest.approx(expected[0] * 2)
        assert peak.output == pytest.approx(expected[1] * 2)
        assert peak.cache_read == pytest.approx(expected[2] * 2)


def test_deepseek_peak_windows_match_announced_hours() -> None:
    for model in _deepseek_models():
        assert model.cost is not None
        peak = model.cost.peak
        assert peak is not None, f"{model.model_name} lost its peak pricing"
        assert peak.timezone == "Asia/Shanghai"
        assert peak.windows == ["09:00-12:00", "14:00-18:00"]
