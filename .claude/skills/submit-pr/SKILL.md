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

## Router Workflow

1. Detect VCS mode:
   - If `.jj/` exists and `jj` is available, use **jj mode**.
   - Otherwise, use **git mode**.

2. Run common checks first:

```bash
git remote -v
gh auth status
```

3. Route by mode:
   - **jj mode**: Read `jj.md` and follow it exactly.
   - **git mode**: Follow the Git workflow below.

## Git Workflow

1. Check status and branch:

```bash
git status --short
git rev-parse --abbrev-ref HEAD
```

2. Determine whether there is PR content:

```bash
git fetch origin main
git log --oneline origin/main..HEAD
```

Decision rule:

- Clean working tree means only "no uncommitted changes".
- Treat "nothing to submit" as true only when there are no uncommitted changes and `origin/main..HEAD` is empty.

3. Run checks:

```bash
make lint
make format
make test
```

If `make format` changes files, commit them first with a Conventional Commit message.

4. Ensure changes are committed, then show included commits:

```bash
git fetch origin main
git log --oneline origin/main..HEAD
```

5. Push branch:

```bash
# If current branch is main, create a feature branch first
# git checkout -b <type>/<short-topic>

git push -u origin <branch-name>
```

6. Create PR:

```bash
cat > .pr_body.md <<'EOF'
## Summary
- change 1
- change 2

## Validation
- make lint
- make format
- make test
EOF

gh pr create \
  --base main \
  --head <branch-name> \
  --title "<conventional-commit-style title>" \
  --label "klaude" \
  --body-file .pr_body.md

rm .pr_body.md
```

7. Verify:

```bash
gh pr view --json url,title,headRefName,baseRefName
```

## Output Requirements

- Report branch name
- Report VCS mode used (`jj` or `git`)
- Report commit hash (if created)
- Report commits included in PR (`git log --oneline origin/main..HEAD`)
- Report PR URL
- Report validation commands and outcomes (`make lint`, `make format`, `make test`)
- Report any blockers clearly

## Common Fixes

If SSH/HTTPS push auth mismatches with `gh` auth:

```bash
gh auth setup-git
```

If teammates use both jj and git, this is fine because PRs are based on remote Git refs.