# pyright: reportPrivateUsage=false
"""Property-based tests for llm.usage module."""

from typing import TYPE_CHECKING

from hypothesis import given, settings
from hypothesis import strategies as st

if TYPE_CHECKING:
    from klaude_code.protocol import llm_param, model


# ============================================================================
# Strategy generators
# ============================================================================


@st.composite
def usage_instances(draw: st.DrawFn) -> "model.Usage":
    """Generate Usage instances with valid token counts."""
    from klaude_code.protocol.model import Usage

    input_tokens = draw(st.integers(min_value=0, max_value=1_000_000))
    cached_tokens = draw(st.integers(min_value=0, max_value=input_tokens))
    output_tokens = draw(st.integers(min_value=0, max_value=1_000_000))
    reasoning_tokens = draw(st.integers(min_value=0, max_value=output_tokens))

    context_limit = draw(st.none() | st.integers(min_value=1, max_value=1_000_000))
    max_tokens = draw(st.none() | st.integers(min_value=1, max_value=100_000))
    context_size = draw(st.none() | st.integers(min_value=0, max_value=1_000_000))

    input_cost = draw(st.none() | st.floats(min_value=0, max_value=100, allow_nan=False))
    output_cost = draw(st.none() | st.floats(min_value=0, max_value=100, allow_nan=False))
    cache_read_cost = draw(st.none() | st.floats(min_value=0, max_value=100, allow_nan=False))

    return Usage(
        input_tokens=input_tokens,
        cached_tokens=cached_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        context_limit=context_limit,
        max_tokens=max_tokens,
        context_size=context_size,
        input_cost=input_cost,
        output_cost=output_cost,
        cache_read_cost=cache_read_cost,
    )


@st.composite
def cost_configs(draw: st.DrawFn) -> "llm_param.Cost":
    """Generate Cost configurations."""
    from klaude_code.protocol.llm_param import Cost

    return Cost(
        input=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
        output=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
        cache_read=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
        currency=draw(st.sampled_from(["USD", "CNY"])),
    )


# ============================================================================
# Property-based tests
# ============================================================================


@given(usage=usage_instances(), cost_config=cost_configs())
@settings(max_examples=100, deadline=None)
def test_calculate_cost_non_negative(usage: "model.Usage", cost_config: "llm_param.Cost") -> None:
    """Property: all calculated costs are non-negative."""
    from klaude_code.llm.usage import calculate_cost
    from klaude_code.protocol.model import Usage

    # Create a fresh usage to avoid mutation issues
    fresh_usage = Usage(
        input_tokens=usage.input_tokens,
        cached_tokens=usage.cached_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_tokens,
    )

    calculate_cost(fresh_usage, cost_config)

    assert fresh_usage.input_cost is not None
    assert fresh_usage.output_cost is not None
    assert fresh_usage.cache_read_cost is not None

    # Non-cached input tokens cost
    # Note: if cached_tokens > input_tokens (invalid state), cost could be negative
    # But we generate valid usage where cached_tokens <= input_tokens
    assert fresh_usage.input_cost >= 0
    assert fresh_usage.output_cost >= 0
    assert fresh_usage.cache_read_cost >= 0


@given(usage=usage_instances())
@settings(max_examples=50, deadline=None)
def test_calculate_cost_no_config_no_change(usage: "model.Usage") -> None:
    """Property: None cost_config leaves usage unchanged."""
    from klaude_code.llm.usage import calculate_cost
    from klaude_code.protocol.model import Usage

    fresh_usage = Usage(
        input_tokens=usage.input_tokens,
        cached_tokens=usage.cached_tokens,
        output_tokens=usage.output_tokens,
    )

    original_input_cost = fresh_usage.input_cost
    original_output_cost = fresh_usage.output_cost

    calculate_cost(fresh_usage, None)

    assert fresh_usage.input_cost == original_input_cost
    assert fresh_usage.output_cost == original_output_cost
