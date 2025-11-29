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


def get_commits_since_tag(tag: str | None) -> list[tuple[str, str]]:
    """Get commits since the given tag. Returns list of (hash, message) tuples."""
    if tag:
        cmd = ["git", "log", f"{tag}..HEAD", "--oneline", "--no-decorate"]
    else:
        cmd = ["git", "log", "--oneline", "--no-decorate"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []

    commits: list[tuple[str, str]] = []
    for line in result.stdout.strip().split("\n"):
        if line:
            parts = line.split(" ", 1)
            if len(parts) == 2:
                commits.append((parts[0], parts[1]))
    return commits


def categorize_commits(
    commits: list[tuple[str, str]],
) -> dict[str, list[tuple[str, str]]]:
    """Categorize commits by conventional commit type."""
    categories: dict[str, list[tuple[str, str]]] = {
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

    for commit_hash, message in commits:
        match = re.match(r"^(\w+)(?:\([^)]+\))?:\s*(.+)$", message)
        if match:
            commit_type = match.group(1).lower()
            description = match.group(2)
            category = type_mapping.get(commit_type, "Other")
        else:
            description = message
            category = "Other"

        categories[category].append((commit_hash, description))

    return {k: v for k, v in categories.items() if v}


def format_changelog_section(version: str, categories: dict[str, list[tuple[str, str]]]) -> str:
    """Format a changelog section for the given version."""
    today = date.today().isoformat()
    lines = [f"## [{version}] - {today}", ""]

    for category, commits in categories.items():
        if commits:
            lines.append(f"### {category}")
            lines.append("")
            for commit_hash, description in commits:
                lines.append(f"- {description} (`{commit_hash}`)")
            lines.append("")

    return "\n".join(lines)


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

    link_section = f"\n[{version}]: https://github.com/inspirepan/klaude-code/compare/{last_tag_name}...{tag_name}"

    if re.search(r"\[Unreleased\]:", content):
        content = re.sub(
            r"(\[Unreleased\]:.*?)$",
            f"[Unreleased]: https://github.com/inspirepan/klaude-code/compare/{tag_name}...HEAD{link_section}",
            content,
            flags=re.MULTILINE,
        )
    else:
        content = (
            content.rstrip()
            + f"\n\n[Unreleased]: https://github.com/inspirepan/klaude-code/compare/{tag_name}...HEAD{link_section}\n"
        )

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
