---
name: submit-pr
description: Use this skill when the user asks to create, submit, or open a GitHub pull request for current changes, including branch push and PR description.
metadata:
  short-description: Push branch and open PR
---

# submit-pr

Create a GitHub pull request for current repository changes using `git` and `gh`.

## When to Use

- User asks to submit a PR
- User asks to push current branch and open a PR
- User asks to create a GitHub pull request from current changes

## Workflow

1. Check repository state:

```bash
git status --short
git rev-parse --abbrev-ref HEAD
git remote -v
gh auth status
```

2. Ensure changes are committed.
   - If there are uncommitted changes, commit them first.
   - Use a Conventional Commit message:

```text
<type>(<scope>): <description>
```

3. If current branch is `main`, create a feature branch first:

```bash
git checkout -b <type>/<short-topic>
```

4. Push branch:

```bash
git push -u origin <branch-name>
```

5. Create PR with `gh pr create`.
   - Prefer `--body-file` to avoid shell escaping and command substitution issues.
   - Example:

```bash
cat > .pr_body.md <<'EOF'
## Summary
- change 1
- change 2

## Validation
- command and result
EOF

gh pr create \
  --base main \
  --head <branch-name> \
  --title "<conventional-commit-style title>" \
  --body-file .pr_body.md

rm .pr_body.md
```

6. Verify and return PR link:

```bash
gh pr view --json url,title,headRefName,baseRefName
```

## Common Fixes

- If SSH push permission fails but `gh` auth is valid, run:

```bash
gh auth setup-git
```

- If remote is HTTPS and push cannot prompt for credentials, run `gh auth setup-git` again.

## Output Requirements

- Report branch name
- Report commit hash (if created)
- Report PR URL
- Report any blockers clearly