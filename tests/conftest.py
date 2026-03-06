import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest


def setup_src_path():
    ROOT = Path(__file__).resolve().parents[1]
    SRC_DIR = ROOT / "src"
    if SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))


setup_src_path()

from klaude_code.session.session import close_default_store


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect HOME/Path.home() to a per-test temp directory and close session stores afterward."""

    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    yield fake_home

    asyncio.run(close_default_store())
