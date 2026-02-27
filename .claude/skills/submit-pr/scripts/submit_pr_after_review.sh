#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  submit_pr_after_review.sh --title <title> --body-file <path> [options]

Required:
  --title <title>         PR title (conventional commit style)
  --body-file <path>      Path to PR body markdown file

Options:
  --head <name>           Branch/bookmark name (required in jj mode; auto-detected in git mode)
  --base <branch>         Base branch (default: main)
  --remote <remote>       Git remote (default: origin)
  --label <label>         PR label (default: klaude)
  --jj-rev <rev>          Revision for jj bookmark (default: @-)
  -h, --help              Show this help

Push reviewed changes and create a PR via gh. Auto-detects jj/git mode.
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

title=""
body_file=""
head_name=""
base_branch="main"
remote="origin"
label="klaude"
jj_rev="@-"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --title)
      [[ $# -ge 2 ]] || die "--title requires a value"
      title="$2"
      shift 2
      ;;
    --body-file)
      [[ $# -ge 2 ]] || die "--body-file requires a value"
      body_file="$2"
      shift 2
      ;;
    --head)
      [[ $# -ge 2 ]] || die "--head requires a value"
      head_name="$2"
      shift 2
      ;;
    --base)
      [[ $# -ge 2 ]] || die "--base requires a value"
      base_branch="$2"
      shift 2
      ;;
    --remote)
      [[ $# -ge 2 ]] || die "--remote requires a value"
      remote="$2"
      shift 2
      ;;
    --label)
      [[ $# -ge 2 ]] || die "--label requires a value"
      label="$2"
      shift 2
      ;;
    --jj-rev)
      [[ $# -ge 2 ]] || die "--jj-rev requires a value"
      jj_rev="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      die "unknown argument: $1"
      ;;
  esac
done

# --- Validate inputs ---
[[ -n "$title" ]] || die "--title is required.
Usage: submit_pr_after_review.sh --title 'feat(scope): description' --body-file /tmp/pr_body.md --head feat/topic"

[[ -n "$body_file" ]] || die "--body-file is required.
Fix: write the PR body to a temp file first, e.g.:
  cat > /tmp/pr_body.md <<'BODY'
  ## Summary
  ...
  BODY
Then pass --body-file /tmp/pr_body.md"

[[ -f "$body_file" ]] || die "Body file not found: $body_file
Fix: ensure the file exists before running this script."

# --- Validate tools ---
command -v git >/dev/null 2>&1 || die "git not found in PATH."
command -v gh >/dev/null 2>&1 || die "gh not found in PATH. Install: https://cli.github.com"

gh auth status >/dev/null 2>&1 || die "gh is not authenticated.
Fix: run 'gh auth login' first."

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Not inside a git repository."
git remote get-url "$remote" >/dev/null 2>&1 || die "Git remote '$remote' does not exist."

# --- Detect VCS mode ---
mode="git"
if [[ -d .jj ]] && command -v jj >/dev/null 2>&1; then
  mode="jj"
fi

# --- Resolve head name ---
if [[ "$mode" == "jj" ]]; then
  [[ -n "$head_name" ]] || die "--head is required in jj mode.
Fix: pass --head <type>/<short-topic>, e.g. --head feat/add-auth"
  jj git fetch --remote "$remote" >/dev/null || die "jj fetch failed from remote '$remote'."
else
  git fetch "$remote" "$base_branch" >/dev/null || die "git fetch failed for '$remote/$base_branch'."
  if [[ -z "$head_name" ]]; then
    head_name="$(git rev-parse --abbrev-ref HEAD)" || die "Failed to detect current git branch."
  fi
  if [[ "$head_name" == "HEAD" ]]; then
    die "Detached HEAD in git mode.
Fix: create a branch first: git checkout -b <type>/<short-topic>
Or pass --head <branch-name> explicitly."
  fi
  if [[ "$head_name" == "$base_branch" ]]; then
    die "Currently on '$base_branch'. Cannot create PR from base branch to itself.
Fix: create a feature branch first: git checkout -b <type>/<short-topic>
Or pass --head <branch-name> explicitly."
  fi
fi

# --- Verify commits exist ---
base_ref="$remote/$base_branch"
compare_rev="HEAD"
compare_ref="HEAD"
if [[ "$mode" == "jj" ]]; then
  compare_rev="$(jj log -r "$jj_rev" --no-graph --template 'commit_id')" || die "Failed to resolve jj revision '$jj_rev'."
  compare_ref="$jj_rev"
fi

commits="$(git log --oneline "$base_ref..$compare_rev")" || die "Failed to list commits from '$base_ref..$compare_ref'."
if [[ -z "$commits" ]]; then
  die "No commits ahead of '$base_ref' at '$compare_ref'. Refusing to create empty PR.
Fix: ensure changes are committed before running this script."
fi

# --- Push ---
if [[ "$mode" == "jj" ]]; then
  jj bookmark set "$head_name" -r "$jj_rev" >/dev/null || die "Failed to set jj bookmark '$head_name' at rev '$jj_rev'.
Fix: verify the revision exists with 'jj log -r $jj_rev'."
  if ! jj git push --bookmark "$head_name" >/dev/null 2>&1; then
    jj bookmark track "$head_name@$remote" >/dev/null 2>&1 || true
    jj git push --bookmark "$head_name" >/dev/null || die "jj push failed for bookmark '$head_name'.
Fix: run 'jj git push --bookmark $head_name' manually to see full error.
If auth issue: run 'gh auth setup-git'."
  fi
else
  git push -u "$remote" "$head_name" >/dev/null || die "git push failed for '$head_name'.
Fix: if auth issue, run 'gh auth setup-git'.
If rejected, pull or rebase first."
fi

# --- Create PR ---
pr_url="$(gh pr create \
  --base "$base_branch" \
  --head "$head_name" \
  --title "$title" \
  --label "$label" \
  --body-file "$body_file" 2>&1)" || die "gh pr create failed: $pr_url
Fix: if PR already exists, use 'gh pr edit' instead.
If label '$label' doesn't exist, retry without --label or create the label first."

# --- Verify ---
pr_view_json="$(gh pr view "$head_name" --json url,title,headRefName,baseRefName 2>&1)" || die "PR created but verification failed.
The PR was likely created successfully. Check: $pr_url"

cat <<EOF
=== PR_SUBMIT_RESULT ===
mode: $mode
base: $base_branch
head: $head_name
title: $title
label: $label
=== PR_COMMITS_BEGIN ===
$commits
=== PR_COMMITS_END ===
=== PR_URL ===
$pr_url
=== PR_VIEW ===
$pr_view_json
EOF
