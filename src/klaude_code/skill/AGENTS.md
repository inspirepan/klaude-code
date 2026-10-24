# Skill Module Guidelines

- Skills are installed independently; never bundle or auto-install skill content.
- Shared user skills live in `~/.agents/skills/`; project skills use `.agents/skills/` or `.claude/skills/`.
- Hidden child directories are not discovered. Directory symlinks are supported.
- Run `uv run pytest tests/skill tests/tui/test_welcome_skill_warnings.py -q --tb=short` after changing discovery.
