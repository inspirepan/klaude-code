# Skill Module Guidelines

## Ownership and Layout

- `src/klaude_code/skill/assets` is a Git submodule.
- Submodule remote: `https://github.com/inspirepan/agent-skills` (branch `main`).
- The parent repo tracks only the submodule pointer, not individual files under `assets/`.

## How to Change Built-in Skills

When changing skill content (files under `assets/`):

1. Commit and push changes in the submodule repo (`agent-skills`).
2. Return to this repo and stage only the updated submodule pointer:
   - `git add src/klaude_code/skill/assets .gitmodules`

Do not try to vendor/copy skill files back into this repo.

## When to Edit Python Code Here

Edit `loader.py`, `manager.py`, or `system_skills.py` only for skill loading/install behavior changes.

## Validation Checklist

- Ensure submodules are initialized before testing:
  - `git submodule update --init --recursive`
- Run focused tests for skill behavior:
  - `uv run pytest tests/test_skill_loader* tests/test_skill_loader_metadata_format.py tests/test_welcome_skill_warnings.py`
