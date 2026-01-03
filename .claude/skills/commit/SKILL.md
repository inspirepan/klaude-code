---
name: commit
description: Use this skill when the user asks to commit, save, or persist their code changes to version control.
metadata:
  short-description: Commit current changes
---

Please follow the steps below to commit your changes with `jj`.

## Workflow

### Step 1: Run pre-commit checks (if not already done)

Skip this step if lint and tests have already been run in the current session.

1. Run the project's linter to check and fix code style issues
2. Run the project's test suite to ensure all tests pass
3. If either check fails, stop the commit process and report the errors to the user
4. If both checks pass, proceed to the next step

### Step 2: Describe changes

Run `jj log` to see working copy changes and all current changes.

For each non-empty change without a description (shows as "(no description set)"):
1. Run `jj diff -r <change_id> --git` to view the diff
2. Read related files if needed to understand the context
3. Use `jj describe -r <change_id>` to add a meaningful description

If changes were made during this conversation, use conversation context to write accurate descriptions.

## Commit Message Format

In order to ensure good formatting, ALWAYS pass the commit message via a HEREDOC:

```bash
jj describe -m "$(cat <<'EOF'
Commit message here.
EOF
)"
```

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
