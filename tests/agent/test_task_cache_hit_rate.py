import asyncio
from pathlib import Path

import pytest

from klaude_code.agent.task import MetadataAccumulator
from klaude_code.protocol import events, message
from klaude_code.protocol.models import Usage

from .agent_harness import create_harness


def test_cache_hit_rate_uses_cache_write_aware_previous_input() -> None:
    acc = MetadataAccumulator(model_name="claude-sonnet-4-6")

    # Anthropic-style split fields before normalization: input_tokens can be tiny,
    # while cache_write_tokens carries most of the prompt.
    acc.add(Usage(input_tokens=3, cached_tokens=0, cache_write_tokens=3_617, output_tokens=10))
    acc.add(Usage(input_tokens=3_620, cached_tokens=3_617, cache_write_tokens=0, output_tokens=12))

    assert acc.last_step_prev_input_tokens == 3_617
    assert acc.last_step_cache_hit_rate is not None
    assert acc.last_step_cache_hit_rate == 1.0


def test_cache_hit_rate_preserves_previous_behavior_without_cache_write() -> None:
    acc = MetadataAccumulator(model_name="gpt-5")

    acc.add(Usage(input_tokens=1_000, cached_tokens=0, output_tokens=10))
    acc.add(Usage(input_tokens=1_100, cached_tokens=800, output_tokens=12))

    assert acc.last_step_prev_input_tokens == 1_000
    assert acc.last_step_cache_hit_rate == 0.8


def test_first_step_restores_cache_baseline_from_previous_task(
    tmp_path: Path,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del isolated_home
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(work_dir=project_dir, monkeypatch=monkeypatch)
        harness.fake_llm.enqueue(
            message.AssistantMessage(
                parts=[message.TextPart(text="first")],
                stop_reason="stop",
                usage=Usage(input_tokens=10_000, output_tokens=10),
            )
        )
        first_events = await harness.run_task("first turn")
        assert not any(isinstance(event, events.CacheHitRateEvent) for event in first_events)

        harness.fake_llm.enqueue(
            message.AssistantMessage(
                parts=[message.TextPart(text="second")],
                stop_reason="stop",
                usage=Usage(input_tokens=11_000, cached_tokens=9_000, output_tokens=10),
            )
        )
        second_events = await harness.run_task("second turn")
        hit_events = [event for event in second_events if isinstance(event, events.CacheHitRateEvent)]

        assert len(hit_events) == 1
        assert hit_events[0].prev_step_input_tokens == 10_000
        assert hit_events[0].cache_hit_rate == 0.9

    asyncio.run(_test())
