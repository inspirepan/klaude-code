#!/usr/bin/env python
"""
Test runner script for klaude-code.

Usage:
    python run_tests.py              # Run all tests
    python run_tests.py tools        # Run only tools tests
    python run_tests.py -v           # Run with verbose output
    python run_tests.py --cov        # Run with coverage report

Note:
    Prefer running tests via `uv run pytest` in normal development.
    This script mirrors that behavior when `uv` is available.
"""

import os
import subprocess
import sys
from pathlib import Path
from shutil import which


def _build_pytest_command() -> list[str]:
    if which("uv") is not None:
        return ["uv", "run", "pytest"]
    return [sys.executable, "-m", "pytest"]


def main():
    project_root = Path(__file__).parent.parent

    # Default pytest arguments
    args = _build_pytest_command()

    env = os.environ.copy()
    src_path = str(project_root / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing_pythonpath else f"{src_path}{os.pathsep}{existing_pythonpath}"

    # Parse command line arguments
    if len(sys.argv) > 1:
        if "--cov" in sys.argv:
            args.extend(["--cov=klaude_code", "--cov-report=html", "--cov-report=term"])
            sys.argv.remove("--cov")

        # Add remaining arguments
        args.extend(sys.argv[1:])

    # Run pytest
    result = subprocess.run(args, cwd=project_root, env=env)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
