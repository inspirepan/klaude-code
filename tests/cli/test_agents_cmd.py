from __future__ import annotations

from klaude_code.cli.agents_cmd import build_agent_inventory, build_json_inventory, build_prime_guide
from klaude_code.config import Config


def _config() -> Config:
    return Config(main_model="sonnet", sub_agent_models={"finder": "flash"})


def test_agent_inventory_includes_main_and_profiles() -> None:
    rows = build_agent_inventory(_config())
    names = [row["name"] for row in rows]
    assert names[0] == "main"
    assert "finder" in names
    assert "code-reviewer" in names
    finder = next(row for row in rows if row["name"] == "finder")
    assert finder["model"] == "flash"


def test_json_inventory_shape() -> None:
    inventory = build_json_inventory(_config())
    assert set(inventory) == {"agent_types", "models", "defaults"}
    assert inventory["defaults"]["main_model"] == "sonnet"
    assert isinstance(inventory["defaults"]["headless_max_running"], int)


def test_prime_guide_mentions_core_loop_and_inventory() -> None:
    guide = build_prime_guide(_config())
    for needle in (
        "klaude run",
        "klaude wait",
        "klaude output",
        "klaude respond",
        "--group",
        "Exit codes",
        "finder",
        "waiting_input",
        "--any",
    ):
        assert needle in guide, f"prime guide is missing: {needle}"
