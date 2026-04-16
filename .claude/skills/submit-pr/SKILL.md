---
name: submit-pr
description: >
  Create a GitHub pull request for current changes. Use when the user asks to
  submit, create, or open a PR. Handles both jj and git repos automatically.
  Do not use for commits only (use commit skill instead).
---

# submit-pr

Push changes and create a GitHub PR via two bundled scripts. Both scripts auto-detect jj/git mode and print actionable error messages on failure -- follow their guidance to resolve issues.

**Only run the 4 steps below. Do not run any extra commands between steps (no `jj log`, `git log`, `jj status`, `gh pr list`, etc.). The scripts handle all checks internally and report errors with fix instructions.**

## Workflow

### 1. Run pre-PR checks

```bash
make lint
make format
make test
```

If any of `make lint`, `make format`, or `make test` fails, you must fix the underlying issue before continuing. Re-run the failed check(s) until they pass, then proceed to step 2.

If `make format` changes files, commit them first:
- jj: `jj describe -m "style: format code" && jj new`
- git: `git add -A && git commit -m "style: format code"`

### 2. Get diff for review

```bash
.claude/skills/submit-pr/scripts/get_pr_diff.sh
```

The script output contains all metadata, commits, and diff. Use it directly to compose a conventional-commit-style PR title and body (summary of changes + validation steps).

If the `PR_COMMITS` section shows a commit with an empty description ("no desc" / blank message) **and that commit has actual changes in the PR diff**, add a description before step 3.

If a commit has an empty description but contributes no diff (for example, an empty jj working-copy/head commit), ignore it.

- For current commit: `jj describe -m "feat(scope): description"`
- For a specific commit in the list: `jj describe -r <sha> -m "feat(scope): description"`

Then re-run `get_pr_diff.sh` and continue only after all commits with real changes have descriptions.

### 3. Submit PR

Write the PR body to a temp file and submit in one step:

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

Extract the PR number and URL from the script output (shown in `PR_URL`) for use in the next step.

### 4. Fix until CI passes

Use the PR number from step 3. Loop until all CI checks pass:

```bash
gh pr checks <pr-number> --watch
```

If any check fails:
1. Read the failed check's logs to identify the root cause.
2. Fix the issue, commit, and push the fix.
3. Run `gh pr checks <pr-number> --watch` again.

Repeat until all checks are green. Do not stop or ask the user for help unless you are stuck after multiple attempts on the same failure.

### 5. Open PR in browser

Once all checks pass, open the PR URL from step 3 and report success to the user:

```bash
open <PR_URL>
```

