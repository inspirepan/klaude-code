---
description: Commit current git changes
---

## Workflow

### Step 1: Detect version control system

Check if `jj` is available in the current environment.

### Step 2A: If jj is available

1. Run `jj status` and `jj log -r 'ancestors(@, 10)'` to see working copy changes and the last 10 changes
2. For each change that has no description (shows as "(no description set)"):
   - Run `jj diff -r <change_id> --git` to view the diff
   - Read related files if needed to understand the context
   - Use `jj describe -r <change_id>` to add a meaningful description

### Step 2B: If jj is not available (git)

1. Run `git status` to check working directory state
2. Run `git diff --cached` to check if there are staged changes
3. If staging area has content:
   - Ask the user: "Staging area has changes. Commit only staged changes, or stage and commit all changes?"
   - If user chooses staged only: proceed with staged changes
   - If user chooses all: run `git add -A` first
4. If staging area is empty:
   - Run `git add -A` to stage all changes
5. Review the changes with `git diff --cached`
6. Create the commit

## Commit Message Format

In order to ensure good formatting, ALWAYS pass the commit message via a HEREDOC:

For jj:
```bash
jj describe -m "$(cat <<'EOF'
Commit message here.
EOF
)"
```

For git:
```bash
git commit -m "$(cat <<'EOF'
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
