"""Build the web frontend and place assets into the Python package directory.

Usage:
    python scripts/build_web.py          # build once
    python scripts/build_web.py --check  # verify dist exists without building

The Vite config already outputs to src/klaude_code/web/dist/, so no copy step
is required. This script automates: install -> build -> verify.

Prefers pnpm when available, falls back to npm.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
DIST_DIR = ROOT / "src" / "klaude_code" / "web" / "dist"


def find_pkg_manager() -> tuple[str, str]:
    """Return (command, name) for the best available package manager."""
    pnpm = shutil.which("pnpm")
    if pnpm:
        return pnpm, "pnpm"
    npm = shutil.which("npm")
    if npm:
        return npm, "npm"
    return "", ""


def run(args: list[str], *, cwd: str | None = None) -> int:
    print(f"+ {' '.join(args)}", flush=True)
    result = subprocess.run(args, check=False, cwd=cwd)
    return result.returncode


def dependencies_installed() -> bool:
    package_json = WEB_DIR / "package.json"
    if not package_json.exists():
        return True

    try:
        package_data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False

    if not isinstance(package_data, dict):
        return False
    package_json_data = cast(dict[str, object], package_data)

    for group_name in ("dependencies", "devDependencies"):
        group_data = package_json_data.get(group_name)
        if not isinstance(group_data, dict):
            continue
        group = cast(dict[str, object], group_data)
        for package_name in group:
            if not (WEB_DIR / "node_modules" / package_name).exists():
                return False

    return True


def ensure_node_modules(cmd: str, name: str) -> bool:
    if dependencies_installed():
        return True
    install_args = [cmd, "install"]
    if name == "pnpm" and (WEB_DIR / "pnpm-lock.yaml").exists():
        install_args.append("--frozen-lockfile")
    return run(install_args, cwd=str(WEB_DIR)) == 0


def build_frontend(cmd: str) -> bool:
    return run([cmd, "run", "build"], cwd=str(WEB_DIR)) == 0


def verify_dist() -> bool:
    index_html = DIST_DIR / "index.html"
    if not index_html.exists():
        print(f"ERROR: {index_html} not found after build", file=sys.stderr)
        return False
    asset_count = sum(1 for _ in DIST_DIR.rglob("*") if _.is_file())
    print(f"Verified web dist: {asset_count} files in {DIST_DIR}")
    return True


def main() -> int:
    check_only = "--check" in sys.argv

    if check_only:
        if verify_dist():
            return 0
        print("Web assets not found. Run: python scripts/build_web.py", file=sys.stderr)
        return 1

    cmd, name = find_pkg_manager()
    if not cmd:
        print("Neither pnpm nor npm found. Install one to build the web UI.", file=sys.stderr)
        return 1

    print(f"Using {name} ({cmd})", flush=True)

    if not ensure_node_modules(cmd, name):
        return 1

    if not build_frontend(cmd):
        return 1

    if not verify_dist():
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
