from klaude_code.core.task import MetadataAccumulator
from klaude_code.protocol import model


def test_cache_hit_rate_uses_cache_write_aware_previous_input() -> None:
    acc = MetadataAccumulator(model_name="claude-sonnet-4-6")

    # Anthropic-style split fields before normalization: input_tokens can be tiny,
    # while cache_write_tokens carries most of the prompt.
    acc.add(model.Usage(input_tokens=3, cached_tokens=0, cache_write_tokens=3_617, output_tokens=10))
    acc.add(model.Usage(input_tokens=3_620, cached_tokens=3_617, cache_write_tokens=0, output_tokens=12))

    assert acc.last_turn_prev_input_tokens == 3_617
    assert acc.last_turn_cache_hit_rate is not None
    assert acc.last_turn_cache_hit_rate == 1.0


def test_cache_hit_rate_preserves_previous_behavior_without_cache_write() -> None:
    acc = MetadataAccumulator(model_name="gpt-5")

    acc.add(model.Usage(input_tokens=1_000, cached_tokens=0, output_tokens=10))
    acc.add(model.Usage(input_tokens=1_100, cached_tokens=800, output_tokens=12))

    assert acc.last_turn_prev_input_tokens == 1_000
    assert acc.last_turn_cache_hit_rate == 0.8
