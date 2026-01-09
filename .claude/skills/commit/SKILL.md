---
name: commit
description: Use this skill when the user asks to commit, save, or persist their code changes to version control and describe current changes.
metadata:
  short-description: Commit current changes
---

Please follow the steps below to commit your changes with `jj` (describe current changes).

Run `jj log -n 5` to see working copy changes and all current changes.

For each non-empty change without a description (shows as "(no description set)"):
1. Run `jj diff -r <change_id> --git` to view the diff
2. Read related files if needed to understand the context
3. Use `jj describe -r <change_id>` to add a meaningful description

If changes were made during this conversation, use conversation context to write accurate descriptions.

## Commit Message Format

Pass the commit message directly with `-m` flag. For multi-line messages, use quoted strings:

```bash
jj describe -m "feat(scope): short description

- Detail line 1
- Detail line 2"
```

Avoid using single quotes or apostrophes in commit messages to prevent shell escaping issues.

## Message Style

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <description>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring (no feature or fix)
- `test`: Adding or updating tests
- `chore`: Build process, dependencies, or tooling changes

Examples:
- `feat(cli): add --verbose flag for debug output`
- `fix(llm): handle API timeout errors gracefully`
- `docs(readme): update installation instructions`
- `refactor(core): simplify session state management`
