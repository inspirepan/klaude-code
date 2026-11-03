from __future__ import annotations

import re

import click
import pytest
from typer.main import get_command
from typer.testing import CliRunner

from klaude_code.cli.main import app


def test_root_help_lists_every_public_command_once() -> None:
    command = get_command(app)
    assert isinstance(command, click.Group)
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    documented = re.findall(r"^  ([a-z][a-z-]*)\s{2,}", result.output, re.MULTILINE)
    public = {name for name, child in command.commands.items() if not child.hidden}
    assert set(documented) == public
    assert len(documented) == len(public)
    assert "Agent? Run: klaude --skill" in result.output
    assert "--json" not in result.output


@pytest.mark.parametrize("name", ["auth", "conf", "kill", "resume"])
def test_replaced_command_names_are_not_registered(name: str) -> None:
    result = CliRunner().invoke(app, [name, "--help"])
    assert result.exit_code == 2
    assert "No such command" in result.output


@pytest.mark.parametrize("name", ["login", "logout", "config", "interrupt", "unpause", "web"])
def test_public_command_help_has_a_description(name: str) -> None:
    command = get_command(app)
    assert isinstance(command, click.Group)
    assert command.commands[name].help
    result = CliRunner().invoke(app, [name, "--help"])
    assert result.exit_code == 0


def test_tasks_help_describes_every_action() -> None:
    command = get_command(app)
    assert isinstance(command, click.Group)
    tasks = command.commands["tasks"]
    assert isinstance(tasks, click.Group)
    result = CliRunner().invoke(app, ["tasks", "--help"])
    assert result.exit_code == 0
    for name, child in tasks.commands.items():
        assert child.help
        assert re.search(rf"^  {name}\s+\S", result.output, re.MULTILINE)
