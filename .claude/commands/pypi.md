---
description: Increment version number, commit changes (excluding debug files), build package, and provide PyPI upload command
---

Help me increment a minor version number, then commit. Then package and upload to PyPI - note that for PyPI upload, just tell me the command, as it requires entering a token.

Note: Exclude any debug code changes, such as debug modifications - don't upload those yet.

Requirements:
1. Find version number files (pyproject.toml and __init__.py)
2. Increment the patch version
3. Only commit version number related changes, excluding specified debug files
4. Build the package
5. Provide PyPI upload command


$ARGUMENTS