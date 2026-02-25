#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///
"""Update CHANGELOG.md with commits since the last tag."""

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_BASE_URL = "https://github.com/inspirepan/klaude-code"


def get_last_tag() -> str | None:
    """Get the most recent git tag."""
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def get_commits_since_tag(tag: str | None) -> list[tuple[str, str, str]]:
    """Get commits since the given tag. Returns list of (hash, subject, body) tuples."""
    if tag:
        cmd = [
            "git",
            "log",
            f"{tag}..HEAD",
            "--first-parent",
            "--no-decorate",
            "--pretty=format:%h%x1f%s%x1f%b%x1e",
        ]
    else:
        cmd = ["git", "log", "--first-parent", "--no-decorate", "--pretty=format:%h%x1f%s%x1f%b%x1e"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []

    commits: list[tuple[str, str, str]] = []
    for entry in result.stdout.strip("\x1e\n").split("\x1e"):
        if not entry.strip():
            continue
        parts = entry.split("\x1f", 2)
        if len(parts) == 3:
            commit_hash, subject, body = parts
            commits.append((commit_hash.strip(), subject.strip(), body.strip()))
    return commits


def extract_pr_metadata(subject: str) -> tuple[str | None, str | None]:
    """Extract PR number and user from a merge commit subject."""
    match = re.match(r"^Merge pull request #(\d+) from ([^/\s]+)/", subject)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def categorize_commits(
    commits: list[tuple[str, str, str]],
) -> dict[str, list[tuple[str, str, str | None, str | None]]]:
    """Categorize commits by conventional commit type."""
    categories: dict[str, list[tuple[str, str, str | None, str | None]]] = {
        "Added": [],
        "Changed": [],
        "Fixed": [],
        "Removed": [],
        "Other": [],
    }

    type_mapping = {
        "feat": "Added",
        "fix": "Fixed",
        "refactor": "Changed",
        "perf": "Changed",
        "docs": "Changed",
        "style": "Changed",
        "test": "Changed",
        "chore": "Other",
        "build": "Other",
        "ci": "Other",
    }

    for commit_hash, subject, body in commits:
        pr_number, pr_user = extract_pr_metadata(subject)
        if pr_number:
            body_lines = [line.strip() for line in body.splitlines() if line.strip()]
            message = body_lines[0] if body_lines else subject
        else:
            message = subject

        match = re.match(r"^(\w+)(?:\([^)]+\))?:\s*(.+)$", message)
        if match:
            commit_type = match.group(1).lower()
            description = match.group(2)
            category = type_mapping.get(commit_type, "Other")
        else:
            description = message
            category = "Other"

        categories[category].append((commit_hash, description, pr_number, pr_user))

    return {k: v for k, v in categories.items() if v}


def format_changelog_section(
    version: str,
    categories: dict[str, list[tuple[str, str, str | None, str | None]]],
) -> str:
    """Format a changelog section for the given version."""
    today = date.today().isoformat()
    lines = [f"## [{version}] - {today}", ""]

    for category, commits in categories.items():
        if commits:
            lines.append(f"### {category}")
            lines.append("")
            for commit_hash, description, pr_number, pr_user in commits:
                if pr_number and pr_user:
                    pr_link = f"{REPO_BASE_URL}/pull/{pr_number}"
                    user_link = f"https://github.com/{pr_user}"
                    lines.append(f"- {description} ([#{pr_number}]({pr_link}) by [@{pr_user}]({user_link}))")
                else:
                    lines.append(f"- {description} (`{commit_hash}`)")
            lines.append("")

    return "\n".join(lines) + "\n"


def update_changelog(version: str, new_section: str, last_tag: str | None) -> None:
    """Update CHANGELOG.md with the new version section."""
    changelog_path = Path("CHANGELOG.md")

    if not changelog_path.exists():
        content = f"""# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

{new_section}
"""
    else:
        content = changelog_path.read_text()

        unreleased_pattern = r"(## \[Unreleased\].*?\n)(.*?)((?=## \[)|$)"
        match = re.search(unreleased_pattern, content, re.DOTALL)

        if match:
            new_content = re.sub(
                unreleased_pattern,
                f"## [Unreleased]\n\n{new_section}",
                content,
                count=1,
                flags=re.DOTALL,
            )
        else:
            header_end = content.find("\n## ")
            if header_end == -1:
                new_content = content + f"\n{new_section}"
            else:
                new_content = content[:header_end] + f"\n{new_section}" + content[header_end:]

        content = new_content

    tag_name = f"v{version}"
    last_tag_name = last_tag if last_tag else f"v{version}"

    link_section = f"\n[{version}]: {REPO_BASE_URL}/compare/{last_tag_name}...{tag_name}"

    if re.search(r"\[Unreleased\]:", content):
        content = re.sub(
            r"(\[Unreleased\]:.*?)$",
            f"[Unreleased]: {REPO_BASE_URL}/compare/{tag_name}...HEAD{link_section}",
            content,
            flags=re.MULTILINE,
        )
    else:
        content = content.rstrip() + f"\n\n[Unreleased]: {REPO_BASE_URL}/compare/{tag_name}...HEAD{link_section}\n"

    changelog_path.write_text(content)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: update_changelog.py <new_version>")
        sys.exit(1)

    new_version = sys.argv[1].lstrip("v")

    last_tag = get_last_tag()
    commits = get_commits_since_tag(last_tag)

    if not commits:
        print("No commits found since last tag")
        sys.exit(0)

    categories = categorize_commits(commits)
    new_section = format_changelog_section(new_version, categories)

    update_changelog(new_version, new_section, last_tag)

    print(f"CHANGELOG.md updated for version {new_version}")
    print(f"  - {len(commits)} commits categorized")
    if last_tag:
        print(f"  - Changes since {last_tag}")


if __name__ == "__main__":
    main()
