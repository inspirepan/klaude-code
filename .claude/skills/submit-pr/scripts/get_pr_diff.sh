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

jj_resolve_commit_id() {
  local rev="$1"
  jj log -r "$rev" --no-graph --template 'commit_id'
}

jj_is_empty_rev() {
  local rev="$1"
  jj log -r "$rev" --no-graph --template 'empty'
}

jj_parent_count() {
  local rev="$1"
  jj log -r "parents($rev)" --no-graph --template 'commit_id ++ "\n"' | sed '/^$/d' | wc -l | tr -d ' '
}

jj_should_skip_empty_rev() {
  local rev="$1"
  [[ "$(jj_is_empty_rev "$rev")" == "true" ]] || return 1
  [[ "$(jj_parent_count "$rev")" -le 1 ]]
}

jj_first_parent_ref() {
  local depth="$1"
  if [[ "$depth" -eq 0 ]]; then
    printf '@'
  else
    printf 'first_parent(@, %s)' "$depth"
  fi
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

head_rev="HEAD"
head_ref="HEAD"
if [[ "$mode" == "jj" ]]; then
  skipped_empty_count=0
  selected_non_default=0
  search_depth=0
  max_search_depth=32
  commits=""

  while [[ "$search_depth" -lt "$max_search_depth" ]]; do
    candidate_ref="$(jj_first_parent_ref "$search_depth")"
    head_ref="$candidate_ref"
    head_rev="$(jj_resolve_commit_id "$candidate_ref" 2>/dev/null || true)"
    if [[ -z "$head_rev" ]]; then
      break
    fi

    commits="$(git log --oneline "$base_ref..$head_rev" 2>/dev/null || true)"
    if [[ -z "$commits" ]]; then
      selected_non_default=1
      search_depth=$((search_depth + 1))
      continue
    fi

    if jj_should_skip_empty_rev "$candidate_ref"; then
      skipped_empty_count=$((skipped_empty_count + 1))
      selected_non_default=1
      search_depth=$((search_depth + 1))
      continue
    fi

    break
  done

  if [[ -n "$commits" && "$selected_non_default" -eq 1 ]]; then
    if [[ "$skipped_empty_count" -gt 0 ]]; then
      echo "Info: auto-selected jj revision '$head_ref' for diff (skipped $skipped_empty_count empty working-copy commit(s))." >&2
    else
      echo "Info: auto-selected jj revision '$head_ref' for diff (newer revisions have no commits ahead of '$base_ref')." >&2
    fi
  fi

  if [[ -z "$head_rev" ]]; then
    commits=""
  fi
fi

if [[ -z "${commits:-}" ]]; then
  commits="$(git log --oneline "$base_ref..$head_rev")" || die "Failed to list commits from '$base_ref..$head_ref'."
fi
if [[ -z "$commits" ]]; then
  die "No commits ahead of '$base_ref' at '$head_ref'. Nothing to include in a PR.
Fix: if you have uncommitted changes, commit them first:
  jj mode: jj describe -m '<msg>' && jj new
  git mode: git add -A && git commit -m '<msg>'
Then re-run this script.
Remaining steps: get diff -> review -> write PR body -> submit PR."
fi

head_sha="$(git rev-parse --short "$head_rev")" || die "Failed to resolve head sha for '$head_ref'."

cat <<EOF
=== PR_DIFF_METADATA ===
mode: $mode
base_ref: $base_ref
head_ref: $head_ref
head_sha: $head_sha
=== PR_COMMITS_BEGIN ===
$commits
=== PR_COMMITS_END ===
=== PR_DIFF_BEGIN ===
EOF

git --no-pager diff --no-color --patch --find-renames "$base_ref...$head_rev" || die "Failed to generate diff from '$base_ref...$head_ref'."

echo "=== PR_DIFF_END ==="
