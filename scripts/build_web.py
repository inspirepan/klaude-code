"""Build the web frontend and place assets into the Python package directory.

Usage:
    python scripts/build_web.py          # build once
    python scripts/build_web.py --check  # verify dist exists without building

The Vite config already outputs to src/klaude_code/web/dist/, so no copy step
is required. This script automates: pnpm install -> pnpm build -> verify.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
DIST_DIR = ROOT / "src" / "klaude_code" / "web" / "dist"


def find_pnpm() -> str | None:
    return shutil.which("pnpm")


def run(args: list[str], *, cwd: str | None = None) -> int:
    print(f"+ {' '.join(args)}", flush=True)
    result = subprocess.run(args, check=False, cwd=cwd)
    return result.returncode


def ensure_node_modules(pnpm: str) -> bool:
    if (WEB_DIR / "node_modules").exists():
        return True
    install_args = [pnpm, "install"]
    if (WEB_DIR / "pnpm-lock.yaml").exists():
        install_args.append("--frozen-lockfile")
    return run(install_args, cwd=str(WEB_DIR)) == 0


def build_frontend(pnpm: str) -> bool:
    return run([pnpm, "build"], cwd=str(WEB_DIR)) == 0


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

    pnpm = find_pnpm()
    if pnpm is None:
        print("pnpm not found. Install pnpm to build the web UI.", file=sys.stderr)
        return 1

    if not ensure_node_modules(pnpm):
        return 1

    if not build_frontend(pnpm):
        return 1

    if not verify_dist():
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
