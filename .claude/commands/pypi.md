---
description: Increment version number, commit changes (excluding debug files), build package, create git tag, and provide PyPI upload command
---

Help me increment the version number, commit changes, package, and publish to PyPI. After successful publication, create and push a git tag for the new version.

Note: Exclude any debug code changes or temporary modifications - keep those separate from the release.

Requirements:
1. Locate version files (pyproject.toml and __init__.py)
2. Increment the patch version number
3. Commit only version-related changes, excluding debug files
4. Build the distribution package
5. Publish to PyPI using `uv publish` (authentication token is pre-configured via environment variable)
6. Create a git tag with the new version (format: v{version})
7. Push the git tag to the remote repository


$ARGUMENTS