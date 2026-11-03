from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from klaude_code.cli.main import app


@pytest.mark.parametrize("existing", [True, False])
def test_config_opens_user_config_or_example(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path, existing: bool
) -> None:
    from klaude_code.config.config import config_path, example_config_path

    assert config_path.is_relative_to(isolated_home)
    monkeypatch.setattr("klaude_code.config.config_path", config_path)
    monkeypatch.setattr("klaude_code.config.example_config_path", example_config_path)
    if existing:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("theme: dark\n")
    calls: list[list[str]] = []

    def run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setenv("EDITOR", "test-editor --wait")
    monkeypatch.setattr("klaude_code.cli.config_cmd.subprocess.run", run)
    result = CliRunner().invoke(app, ["config"])

    assert result.exit_code == 0, result.output
    target = config_path if existing else example_config_path
    assert calls == [["test-editor", "--wait", str(target)]]
    assert target.is_file()
