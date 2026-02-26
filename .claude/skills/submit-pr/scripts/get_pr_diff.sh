#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  get_pr_diff.sh [--base <branch>] [--remote <remote>]

Auto-detect jj/git mode, fetch latest base, print PR commit list and diff patch.

Output sections (stdout):
  === PR_DIFF_METADATA ===
  === PR_COMMITS_BEGIN === ... === PR_COMMITS_END ===
  === PR_DIFF_BEGIN === ... === PR_DIFF_END ===
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

base_branch="main"
remote="origin"

while [[ $# -gt 0 ]]; do
  case "$1" in
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

command -v git >/dev/null 2>&1 || die "git not found in PATH. Install git first."
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Not inside a git repository. cd into the repo root first."

git remote get-url "$remote" >/dev/null 2>&1 || die "Git remote '$remote' does not exist.
Fix: run 'git remote add $remote <url>' or pass --remote <name>."

mode="git"
if [[ -d .jj ]] && command -v jj >/dev/null 2>&1; then
  mode="jj"
fi

base_ref="$remote/$base_branch"

if [[ "$mode" == "jj" ]]; then
  jj git fetch --remote "$remote" >/dev/null 2>&1 || die "jj fetch failed from remote '$remote'.
Fix: check network connectivity and run 'jj git fetch --remote $remote' manually."
else
  git fetch "$remote" "$base_branch" >/dev/null || die "git fetch failed for '$base_ref'.
Fix: check network connectivity and run 'git fetch $remote $base_branch' manually."
fi

commits="$(git log --oneline "$base_ref..HEAD")" || die "Failed to list commits from '$base_ref..HEAD'."
if [[ -z "$commits" ]]; then
  die "No commits ahead of '$base_ref'. Nothing to include in a PR.
Fix: if you have uncommitted changes, commit them first:
  jj mode: jj describe -m '<msg>' && jj new
  git mode: git add -A && git commit -m '<msg>'
Then re-run this script.
Remaining steps: get diff -> review -> write PR body -> submit PR."
fi

head_sha="$(git rev-parse --short HEAD)" || die "Failed to resolve HEAD sha."

cat <<EOF
=== PR_DIFF_METADATA ===
mode: $mode
base_ref: $base_ref
head_ref: HEAD
head_sha: $head_sha
=== PR_COMMITS_BEGIN ===
$commits
=== PR_COMMITS_END ===
=== PR_DIFF_BEGIN ===
EOF

git --no-pager diff --no-color --patch --find-renames "$base_ref...HEAD" || die "Failed to generate diff from '$base_ref...HEAD'."

echo "=== PR_DIFF_END ==="
