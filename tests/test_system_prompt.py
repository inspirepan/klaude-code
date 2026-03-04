from __future__ import annotations

from pathlib import Path

from klaude_code.core.prompts.system_prompt import _build_env_info  # pyright: ignore[reportPrivateUsage]


def test_build_env_info_handles_missing_work_dir(tmp_path: Path) -> None:
    missing_dir = tmp_path / "workspace"

    env_info = _build_env_info("gpt-5.3-codex", missing_dir)

    assert f"Working directory: {missing_dir} (not found)" in env_info
    assert "Current directory is not a git repo" in env_info
