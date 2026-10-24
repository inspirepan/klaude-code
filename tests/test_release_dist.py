"""Release artifact checks must reject packages with missing bundled assets."""

import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile

import pytest


@pytest.mark.parametrize(
    ("artifact", "missing"),
    [
        (None, None),
        ("wheel", "server/web/index.html"),
        ("wheel", "server/web/assets/index-test.js"),
        ("sdist", "server/web/assets/index-test.css"),
        ("sdist", "server/web/favicon.svg"),
    ],
)
def test_verify_release_dist(tmp_path: Path, artifact: str | None, missing: str | None) -> None:
    script_path = Path(".claude/skills/publish/scripts/verify_dist.py")
    script = tmp_path / script_path
    script.parent.mkdir(parents=True)
    shutil.copyfile(script_path, script)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    files = {
        "server/web/index.html": b'<script src="/assets/index-test.js"></script>',
        "server/web/assets/index-test.js": b"console.log('ok')",
        "server/web/assets/index-test.css": b"body { color: black }",
        "server/web/favicon.svg": b"<svg/>",
    }
    for name, content in files.items():
        path = tmp_path / "src" / "klaude_code" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    dist = tmp_path / "dist"
    dist.mkdir()
    with ZipFile(dist / "klaude_code-1.0.0-py3-none-any.whl", "w") as wheel:
        for name, content in files.items():
            if artifact != "wheel" or name != missing:
                wheel.writestr(f"klaude_code/{name}", content)
    with tarfile.open(dist / "klaude_code-1.0.0.tar.gz", "w:gz") as sdist:
        for name, content in files.items():
            if artifact != "sdist" or name != missing:
                info = tarfile.TarInfo(f"klaude_code-1.0.0/src/klaude_code/{name}")
                info.size = len(content)
                sdist.addfile(info, io.BytesIO(content))

    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False)
    if missing is None:
        assert result.returncode == 0, result.stderr
        assert "Verified bundled web assets" in result.stdout
    else:
        assert result.returncode != 0
        assert "missing bundled assets" in result.stderr
        assert missing in result.stderr
