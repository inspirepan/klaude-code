---
name: commit
description: Use this skill when the user asks to commit, save, or persist their code changes to version control and describe current changes.
metadata:
  short-description: Commit current changes
---

Use the workflow below to commit changes with either `jj` or `git`.

## Workflow

1. Detect VCS mode:
   - If `.jj/` exists and `jj` is available, use **jj mode**.
   - Otherwise, use **git mode**.

2. **jj mode**
   - Run `jj log -n 5` to inspect working-copy and recent changes.
   - For each non-empty change without a description (`(no description set)`):
     1. Run `jj diff -r <change_id> --git`.
     2. Read related files if needed.
     3. Set description with `jj describe -r <change_id> -m "<message>"`.

3. **git mode**
   - Run `git status --short`.
   - Review diff with `git diff` (and `git diff --staged` if needed).
   - Stage changes (`git add -A` or targeted files).
   - Commit with `git commit -m "<message>"`.

If changes were made during this conversation, use conversation context to write accurate descriptions/messages.

## Commit Message Format

Pass the commit message directly with `-m` flag. For multi-line messages, use quoted strings:

```bash
jj describe -m "feat(scope): short description

- Detail line 1
- Detail line 2"

git commit -m "feat(scope): short description

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
