from klaude_code.cli.cost_cmd import COST_CACHE_VERSION


def test_cost_cache_version_includes_cache_write_tokens_schema() -> None:
    assert COST_CACHE_VERSION >= 2