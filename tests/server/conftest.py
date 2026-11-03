from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from klaude_code.server.read_only import create_read_only_app
from klaude_code.server.system_context import clear_cache
from klaude_code.session import Session


@dataclass
class WebEnv:
    client: TestClient
    work_dir: Path
    home_dir: Path

    def create_session(self) -> str:
        session = Session.create(work_dir=self.work_dir)
        session.ensure_meta_exists()
        return session.id


@pytest.fixture
def app_env(tmp_path: Path, isolated_home: Path):
    clear_cache()
    work = tmp_path / "work"
    work.mkdir()
    with TestClient(create_read_only_app(home_dir=isolated_home)) as client:
        yield WebEnv(client=client, work_dir=work, home_dir=isolated_home)
