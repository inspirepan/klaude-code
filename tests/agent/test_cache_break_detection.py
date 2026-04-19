from __future__ import annotations

from pathlib import Path

from klaude_code.agent.cache_break_detection import CacheTracker
from klaude_code.protocol import llm_param
from klaude_code.protocol.models import Usage


def _make_tools(*names: str) -> list[llm_param.ToolSchema]:
    return [llm_param.ToolSchema(name=n, type="function", description=f"tool {n}", parameters={}) for n in names]


def _make_usage(cached: int = 0, input_tokens: int = 0, cache_write: int = 0) -> Usage:
    return Usage(cached_tokens=cached, input_tokens=input_tokens, cache_write_tokens=cache_write)


class TestCacheTrackerHitRate:
    def test_first_turn_no_hit_rate(self) -> None:
        t = CacheTracker()
        t.update(_make_usage(cached=0, input_tokens=1000))
        assert t.last_hit_rate is None

    def test_second_turn_hit_rate(self) -> None:
        t = CacheTracker()
        t.update(_make_usage(cached=0, input_tokens=10_000))
        t.update(_make_usage(cached=9_000, input_tokens=11_000))
        assert t.last_hit_rate is not None
        assert abs(t.last_hit_rate - 0.9) < 0.01

    def test_avg_hit_rate(self) -> None:
        t = CacheTracker()
        t.update(_make_usage(cached=0, input_tokens=10_000))
        t.update(_make_usage(cached=10_000, input_tokens=12_000))  # 1.0
        t.update(_make_usage(cached=6_000, input_tokens=14_000))  # 0.5
        assert t.avg_hit_rate is not None
        assert abs(t.avg_hit_rate - 0.75) < 0.01

    def test_prev_turn_input_tokens_uses_max(self) -> None:
        t = CacheTracker()
        # cached + cache_write > input_tokens
        t.update(_make_usage(cached=8_000, input_tokens=5_000, cache_write=4_000))
        assert t.prev_turn_input_tokens == 12_000  # max(5000, 8000+4000)


class TestCacheTrackerBreakDetection:
    def test_first_call_no_report(self) -> None:
        t = CacheTracker()
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        assert t.update(_make_usage(cached=50_000, input_tokens=60_000)) is None

    def test_stable_cache_no_report(self) -> None:
        t = CacheTracker()
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        t.update(_make_usage(cached=50_000, input_tokens=60_000))
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        assert t.update(_make_usage(cached=50_000, input_tokens=70_000)) is None

    def test_small_drop_no_report(self) -> None:
        t = CacheTracker()
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        t.update(_make_usage(cached=50_000, input_tokens=60_000))
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        # 1000 drop, below threshold
        assert t.update(_make_usage(cached=49_000, input_tokens=60_000)) is None

    def test_significant_drop_reports(self) -> None:
        t = CacheTracker()
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        t.update(_make_usage(cached=50_000, input_tokens=60_000))
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        report = t.update(_make_usage(cached=10_000, input_tokens=60_000))
        assert report is not None
        assert report.token_drop == 40_000

    def test_report_message_is_multiline_and_readable(self) -> None:
        t = CacheTracker()
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        t.update(_make_usage(cached=50_000, input_tokens=60_000))
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        report = t.update(_make_usage(cached=10_000, input_tokens=60_000))

        assert report is not None
        summary_lines = report.summary.splitlines()
        assert summary_lines[0].startswith("Prompt cache break detected: ")
        assert summary_lines[1] == "Cached tokens: 50,000 -> 10,000 (drop: 40,000)"
        assert report.format_message("/tmp/cache-break.txt").splitlines() == [
            *summary_lines,
            "Report: /tmp/cache-break.txt",
        ]

    def test_system_prompt_change_detected(self) -> None:
        t = CacheTracker()
        t.record_pre_call_state("prompt v1", _make_tools("bash"), "claude-sonnet-4-20250514")
        t.update(_make_usage(cached=50_000, input_tokens=60_000))
        t.record_pre_call_state("prompt v2 longer", _make_tools("bash"), "claude-sonnet-4-20250514")
        report = t.update(_make_usage(cached=10_000, input_tokens=60_000))
        assert report is not None
        assert "system prompt changed" in report.reason

    def test_model_change_detected(self) -> None:
        t = CacheTracker()
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        t.update(_make_usage(cached=50_000, input_tokens=60_000))
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-opus-4-20250514")
        report = t.update(_make_usage(cached=0, input_tokens=60_000))
        assert report is not None
        assert "model changed" in report.reason

    def test_tool_change_detected(self) -> None:
        t = CacheTracker()
        t.record_pre_call_state("prompt", _make_tools("bash", "read"), "claude-sonnet-4-20250514")
        t.update(_make_usage(cached=50_000, input_tokens=60_000))
        t.record_pre_call_state("prompt", _make_tools("bash", "read", "write"), "claude-sonnet-4-20250514")
        report = t.update(_make_usage(cached=10_000, input_tokens=60_000))
        assert report is not None
        assert "tools changed" in report.reason

    def test_compaction_resets_baseline(self) -> None:
        t = CacheTracker()
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        t.update(_make_usage(cached=50_000, input_tokens=60_000))
        t.notify_compaction()
        t.record_pre_call_state("prompt", _make_tools("bash"), "claude-sonnet-4-20250514")
        assert t.update(_make_usage(cached=10_000, input_tokens=30_000)) is None

    def test_report_write(self) -> None:
        t = CacheTracker()
        t.record_pre_call_state("prompt v1", _make_tools("bash"), "claude-sonnet-4-20250514")
        t.update(_make_usage(cached=50_000, input_tokens=60_000))
        t.record_pre_call_state("prompt v2", _make_tools("bash"), "claude-sonnet-4-20250514")
        report = t.update(_make_usage(cached=10_000, input_tokens=60_000))
        assert report is not None
        path_str = report.write_report()
        path = Path(path_str)
        assert path.exists()
        content = path.read_text()
        assert "Prompt Cache Break Report" in content
