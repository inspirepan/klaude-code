# Skill Module Guidelines

- Bundle `klaude-config` and `klaude-session-logs` and sync them to `~/.klaude/skills/`.
- Use a manifest to preserve locally modified skills and user-deleted skills during sync.
- Shared user skills live in `~/.agents/skills/`; project skills use `.agents/skills/` or `.claude/skills/`.
- Same-name project skills override user skills; user directories follow the order in `docs/configuration.md`.
- Hidden child directories are not discovered. Directory symlinks are supported.
- Run `uv run pytest tests/skill tests/tui/test_welcome_skill_warnings.py -q --tb=short` after changing discovery.
