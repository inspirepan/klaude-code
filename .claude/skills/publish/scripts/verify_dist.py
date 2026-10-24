#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Verify the current release includes the built web viewer and system skills."""

import tarfile
import tomllib
from pathlib import Path
from zipfile import ZipFile


def main() -> None:
    root = Path(__file__).resolve().parents[4]
    with (root / "pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]

    package = root / "src" / "klaude_code"
    web = package / "server" / "web"
    for pattern in ("index.html", "favicon.svg", "assets/*.js", "assets/*.css"):
        if not any(path.is_file() and path.stat().st_size for path in web.glob(pattern)):
            raise SystemExit(f"Web bundle is missing {pattern}; run make web before building the package")

    required = {f"klaude_code/{path.relative_to(package).as_posix()}" for path in web.rglob("*") if path.is_file()}
    stem = f"klaude_code-{version}"
    wheel = root / "dist" / f"{stem}-py3-none-any.whl"
    sdist = root / "dist" / f"{stem}.tar.gz"
    for artifact in (wheel, sdist):
        if not artifact.is_file():
            raise SystemExit(f"Missing release artifact: {artifact.name}; run make build")

    with ZipFile(wheel) as archive:
        missing = sorted(required - set(archive.namelist()))
    if missing:
        raise SystemExit(f"{wheel.name} is missing bundled assets: {', '.join(missing)}")
    print(f"Verified bundled web assets in {wheel.name}", flush=True)

    with tarfile.open(sdist) as archive:
        missing = sorted({f"{stem}/src/{name}" for name in required} - set(archive.getnames()))
    if missing:
        raise SystemExit(f"{sdist.name} is missing bundled assets: {', '.join(missing)}")
    print(f"Verified bundled web assets in {sdist.name}", flush=True)


if __name__ == "__main__":
    main()
