---
name: publish
description: Publish a new version of klaude-code to PyPI. This skill handles version bumping, changelog updates, git tagging, and package publishing. Use when the user wants to release a new version.
---

# Publish Skill

This skill manages the release process for klaude-code, including version management, changelog updates, git tagging, and PyPI publishing.

## Prerequisites

- `UV_PUBLISH_TOKEN` environment variable must be set for PyPI publishing
- Working directory must be the klaude-code repository root
- Git repository must be clean (no uncommitted changes)
- Git submodules must be initialized and up-to-date (`src/klaude_code/skill/assets`)
- Node.js and pnpm (preferred) or npm must be available to build the web viewer

Before starting the release workflow, run:

```bash
git submodule sync --recursive
git submodule update --init --recursive
```

## Release Workflow

### Step 1: Determine Version Bump Type

Ask the user which version bump type to apply:
- `major` - Breaking changes (X.0.0)
- `minor` - New features, backwards compatible (x.Y.0)
- `patch` - Bug fixes, backwards compatible (x.y.Z)

### Step 2: Run Version Bump Script

Execute the version bump script to update `pyproject.toml`:

```bash
uv run .claude/skills/publish/scripts/bump_version.py <bump_type>
```

The script will:
1. Read current version from `pyproject.toml`
2. Calculate new version based on bump type
3. Update `pyproject.toml` with new version
4. Output the old and new version numbers

### Step 3: Update CHANGELOG.md

Execute the changelog update script:

```bash
uv run .claude/skills/publish/scripts/update_changelog.py <new_version>
```

The script will:
1. Get commits since the last tag
2. Categorize commits by type (feat, fix, refactor, etc.)
3. Update CHANGELOG.md with the new version section
4. Move [Unreleased] changes to the new version

### Step 4: Validate and Build

Inspect the commits being released relative to `origin/main`, then run all required checks before creating the release commit or pushing:

```bash
jj log -r 'main@origin..@'
jj diff --from main@origin
make pre-push
```

`make pre-push` formats, lints, tests, and runs `make build`. The build first runs `make web`, then builds the sdist and wheel and executes `scripts/verify_dist.py`. Verification checks the current version's two artifacts for the complete web bundle and system skill files, including references and scripts; it does not select an older wheel from `dist/`.

Review any formatting changes before committing. If formatting changed files, rerun the affected checks. Stop if any check or artifact verification fails; do not tag, push, or publish an unverified release.

### Step 5: Commit and Tag

This project uses jj (Jujutsu) in colocated mode with git. Create a release commit and tag:

```bash
# Describe current change as release commit
jj describe -m "chore(release): 发布 v<new_version>"

# Create new empty change for future work
jj new

# Get the git commit id of the release commit (jj's @- syntax doesn't work with git)
jj log -r @- -T 'commit_id' --no-graph

# Create tag using the git commit id
git tag v<new_version> <commit_id>
```

### Step 6: Push Changes

Push the commit and tag to remote:

```bash
# Move main bookmark to the verified release commit, then push only main
jj bookmark set main -r @-
jj git push --bookmark main

# Push the tag
git push origin v<new_version>
```

The submodule commit must already be available on its remote before pushing the release. Initializing a local submodule does not publish its commits.

### Step 7: Publish Verified Artifacts

Publish only the current version's artifacts built and verified in Step 4. Do not rebuild after tagging without rerunning validation; the published package must match the release commit.

```bash
uv run .claude/skills/publish/scripts/verify_dist.py
uv publish dist/klaude_code-<new_version>-py3-none-any.whl dist/klaude_code-<new_version>.tar.gz
```

Do not use bare `uv publish`: `dist/` may contain artifacts from older versions. Do not publish if verification fails.

## Error Handling

- If git working directory is dirty, prompt user to commit or stash changes first
- If UV_PUBLISH_TOKEN is not set, warn user before publishing step
- If any step fails, provide clear error message and recovery instructions

## Scripts

- `scripts/bump_version.py` - Handles semantic version bumping
- `scripts/update_changelog.py` - Updates CHANGELOG.md with commits since last tag
- `scripts/verify_dist.py` - Checks the current wheel and sdist include the built web viewer and required system skills
