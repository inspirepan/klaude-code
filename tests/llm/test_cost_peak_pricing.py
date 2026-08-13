"""Time-of-day (peak / off-peak) pricing."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from klaude_code.llm.usage import calculate_cost
from klaude_code.protocol import llm_param
from klaude_code.protocol.models import Usage

BEIJING = ZoneInfo("Asia/Shanghai")


def _deepseek_like_cost() -> llm_param.Cost:
    return llm_param.Cost(
        input=1.5,
        output=4.5,
        cache_read=0.05,
        currency="CNY",
        peak=llm_param.PeakCost(
            windows=["09:00-12:00", "14:00-18:00"],
            timezone="Asia/Shanghai",
            input=3,
            output=9,
            cache_read=0.1,
        ),
    )


def test_cost_without_peak_returns_self() -> None:
    cost = llm_param.Cost(input=1, output=2)
    assert cost.at(datetime(2026, 8, 17, 10, 0, tzinfo=BEIJING)) is cost


@pytest.mark.parametrize(
    ("hour", "minute"),
    [(9, 0), (11, 59), (14, 0), (17, 59)],
)
def test_peak_window_selects_peak_price(hour: int, minute: int) -> None:
    cost = _deepseek_like_cost().at(datetime(2026, 8, 17, hour, minute, tzinfo=BEIJING))

    assert (cost.input, cost.output, cost.cache_read) == (3, 9, 0.1)
    assert cost.currency == "CNY"
    # Resolved table is a plain price list: no second resolution pass.
    assert cost.peak is None


@pytest.mark.parametrize(
    ("hour", "minute"),
    [(0, 0), (8, 59), (12, 0), (13, 59), (18, 0), (23, 59)],
)
def test_off_peak_hours_keep_base_price(hour: int, minute: int) -> None:
    cost = _deepseek_like_cost().at(datetime(2026, 8, 17, hour, minute, tzinfo=BEIJING))

    assert (cost.input, cost.output, cost.cache_read) == (1.5, 4.5, 0.05)


def test_peak_window_uses_configured_timezone_not_local_clock() -> None:
    # 02:00 UTC == 10:00 Beijing -> peak.
    cost = _deepseek_like_cost().at(datetime(2026, 8, 17, 2, 0, tzinfo=UTC))
    assert cost.input == 3

    # 02:00 Beijing == 18:00 UTC (previous day) -> off-peak.
    cost = _deepseek_like_cost().at(datetime(2026, 8, 16, 18, 0, tzinfo=UTC))
    assert cost.input == 1.5


def test_window_crossing_midnight() -> None:
    cost = llm_param.Cost(
        input=10,
        peak=llm_param.PeakCost(windows=["22:00-02:00"], timezone="Asia/Shanghai", input=20),
    )

    assert cost.at(datetime(2026, 8, 17, 22, 30, tzinfo=BEIJING)).input == 20
    assert cost.at(datetime(2026, 8, 17, 1, 59, tzinfo=BEIJING)).input == 20
    assert cost.at(datetime(2026, 8, 17, 2, 0, tzinfo=BEIJING)).input == 10
    assert cost.at(datetime(2026, 8, 17, 12, 0, tzinfo=BEIJING)).input == 10


def test_unset_peak_price_falls_back_to_off_peak_price() -> None:
    cost = llm_param.Cost(
        input=1,
        output=2,
        cache_read=0.1,
        peak=llm_param.PeakCost(windows=["00:00-24:00"], input=5),
    )

    resolved = cost.at(datetime(2026, 8, 17, 10, 0, tzinfo=BEIJING))
    assert (resolved.input, resolved.output, resolved.cache_read) == (5, 2, 0.1)


def test_empty_windows_never_peak() -> None:
    cost = llm_param.Cost(input=1, peak=llm_param.PeakCost(input=5))
    assert cost.at(datetime(2026, 8, 17, 10, 0, tzinfo=BEIJING)).input == 1


def test_unknown_timezone_falls_back_to_off_peak() -> None:
    cost = llm_param.Cost(
        input=1,
        peak=llm_param.PeakCost(windows=["00:00-24:00"], timezone="Mars/Olympus", input=5),
    )
    assert cost.at(datetime(2026, 8, 17, 10, 0, tzinfo=BEIJING)).input == 1


def test_invalid_window_is_rejected_at_config_load() -> None:
    with pytest.raises(ValidationError):
        llm_param.PeakCost(windows=["9-12"])

    with pytest.raises(ValidationError):
        llm_param.PeakCost(windows=["09:00-25:00"])


def test_calculate_cost_uses_request_time_tier() -> None:
    usage = Usage(input_tokens=1_200_000, cached_tokens=200_000, output_tokens=1_000_000)
    calculate_cost(usage, _deepseek_like_cost(), at=datetime(2026, 8, 17, 10, 0, tzinfo=BEIJING))

    assert usage.currency == "CNY"
    assert usage.input_cost == pytest.approx(3.0)  # 1M non-cached input @ 3
    assert usage.cache_read_cost == pytest.approx(0.02)  # 0.2M cache read @ 0.1
    assert usage.output_cost == pytest.approx(9.0)  # 1M output @ 9

    usage = Usage(input_tokens=1_200_000, cached_tokens=200_000, output_tokens=1_000_000)
    calculate_cost(usage, _deepseek_like_cost(), at=datetime(2026, 8, 17, 20, 0, tzinfo=BEIJING))

    assert usage.input_cost == pytest.approx(1.5)
    assert usage.cache_read_cost == pytest.approx(0.01)
    assert usage.output_cost == pytest.approx(4.5)
