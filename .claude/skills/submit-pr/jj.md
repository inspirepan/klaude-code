# submit-pr (jj mode)

Use this workflow only when `.jj/` exists and `jj` is available.

## 1) Check repository and auth state

Run:

```bash
git remote -v
gh auth status
jj status
jj log -n 5
```

## 2) Determine whether there is PR content

Run:

```bash
jj git fetch --remote origin
git log --oneline origin/main..HEAD
```

Decision rules:

1. `jj status` clean only means "no uncommitted file changes".
2. A clean working copy does **not** mean "no PR content".
3. Only treat "nothing to submit" as true when **both** are true:
   - no uncommitted changes, and
   - `git log --oneline origin/main..HEAD` is empty.

## 3) Run pre-PR checks

Run:

```bash
make lint
make format
make test
```

If `make format` changes files, include those changes in a commit before creating PR.

## 4) Ensure all intended changes are committed

If there are uncommitted changes, create/update the current jj change with a Conventional Commit message, then create a new empty working copy change:

```bash
jj describe -m "<type>(<scope>): <description>"
jj new
```

## 5) Show commits that will be in PR

Run:

```bash
jj git fetch --remote origin
git log --oneline origin/main..HEAD
```

If this is empty, stop and report blocker: no commits ahead of `origin/main`.

## 6) Prepare bookmark and push

Set bookmark to the latest finished change (not the empty working-copy commit):

```bash
jj bookmark set <branch-name> -r @-
jj git push --bookmark <branch-name>
```

Use a branch name like `<type>/<short-topic>`.

## 7) Create PR with gh

Use `--body-file` and always include `klaude` label:

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

## 8) Verify and report

Run:

```bash
gh pr view --json url,title,headRefName,baseRefName
```

Return:

- VCS mode: `jj`
- branch/bookmark name
- commit hash (if newly created)
- commits included (`git log --oneline origin/main..HEAD`)
- validation commands and outcomes
- PR URL
- blockers (if any)

## Common fixes

If push/auth mismatches happen:

```bash
gh auth setup-git
```