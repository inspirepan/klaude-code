---
name: submit-pr
description: Use this skill when the user asks to create, submit, or open a GitHub pull request for current changes, including branch push and PR description.
metadata:
  short-description: Push branch and open PR
---

# submit-pr

Create a GitHub pull request for current repository changes using `gh` with either `jj` or `git`.

## When to Use

- User asks to submit a PR
- User asks to push current branch and open a PR
- User asks to create a GitHub pull request from current changes

## Workflow

1. Detect VCS mode:
   - If `.jj/` exists and `jj` is available, use **jj mode**.
   - Otherwise, use **git mode**.

2. Check repository state:

Common:

```bash
git remote -v
gh auth status
```

jj mode:

```bash
jj status
jj log -n 5
```

git mode:

```bash
git status --short
git rev-parse --abbrev-ref HEAD
```

3. Run pre-PR checks:

```bash
make lint
make format
make test
```

   - If `make format` updates files, include those updates in your commit.

4. Ensure changes are committed.
   - If there are uncommitted changes, commit them first.
   - In jj mode, ensure relevant changes have meaningful descriptions.
   - Use a Conventional Commit message:

```text
<type>(<scope>): <description>
```

5. Show commits that will be included in the PR:

jj mode:

```bash
jj git fetch --remote origin
git log --oneline origin/main..HEAD
```

git mode:

```bash
git fetch origin main
git log --oneline origin/main..HEAD
```

6. Prepare branch/bookmark and push:

jj mode:

```bash
jj bookmark set <branch-name> -r @
jj git push --bookmark <branch-name>
```

git mode:

```bash
# If current branch is main, create a feature branch first
# git checkout -b <type>/<short-topic>

# Push the branch you plan to use for PR
git push -u origin <branch-name>
```

7. Create PR with `gh pr create`.
   - Prefer `--body-file` to avoid shell escaping and command substitution issues.
   - Always add the `klaude` label when creating the PR.
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
  --label "klaude" \
  --body-file .pr_body.md

rm .pr_body.md
```

8. Verify and return PR link:

```bash
gh pr view --json url,title,headRefName,baseRefName
```

## Common Fixes

- If SSH push permission fails but `gh` auth is valid, run:

```bash
gh auth setup-git
```

- If remote is HTTPS and push cannot prompt for credentials, run `gh auth setup-git` again.

- If teammates use both jj and git: this is fine. PR is based on remote Git branches, so both tools interoperate through the same remote refs.

## Output Requirements

- Report branch name
- Report VCS mode used (`jj` or `git`)
- Report commit hash (if created)
- Report commits included in PR (`git log --oneline origin/main..HEAD`)
- Report PR URL
- Report validation commands and outcomes (`make lint`, `make format`, `make test`)
- Report any blockers clearly