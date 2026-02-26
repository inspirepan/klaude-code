---
name: submit-pr
description: >
  Create a GitHub pull request for current changes. Use when the user asks to
  submit, create, or open a PR. Handles both jj and git repos automatically.
  Do not use for commits only (use commit skill instead).
---

# submit-pr

Push changes and create a GitHub PR via two bundled scripts. Both scripts auto-detect jj/git mode and print actionable error messages on failure -- follow their guidance to resolve issues.

## Workflow

### 1. Run pre-PR checks

```bash
make lint
make format
make test
```

If `make format` changes files, commit them first:
- jj: `jj describe -m "style: format code" && jj new`
- git: `git add -A && git commit -m "style: format code"`

### 2. Get diff for review

```bash
.claude/skills/submit-pr/scripts/get_pr_diff.sh
```

Review the output. Determine a conventional-commit-style PR title and write a PR body covering: summary of changes, validation steps run.

### 3. Submit PR

Write the PR body to a temp file, then run:

```bash
cat > /tmp/pr_body.md <<'EOF'
## Summary
- ...

## Validation
- make lint
- make format
- make test
EOF

.claude/skills/submit-pr/scripts/submit_pr_after_review.sh \
  --title "feat(scope): description" \
  --body-file /tmp/pr_body.md \
  --head <type>/<short-topic>
```

`--head` is required in jj mode, auto-detected in git mode.

Report the PR URL from script output to the user.
