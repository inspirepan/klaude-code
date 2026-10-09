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

from klaude_code.auth import base as auth_base  # noqa: E402
from klaude_code.auth import env as auth_env  # noqa: E402
from klaude_code.config import config as config_module  # noqa: E402
from klaude_code.config.builtin_config import SUPPORTED_API_KEYS  # noqa: E402
from klaude_code.config.loader import load_config  # noqa: E402
from klaude_code.session.store_registry import close_default_store  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_local_credentials(request: pytest.FixtureRequest) -> Iterator[None]:
    """Only network tests may inherit developer credentials and user files."""
    network = request.node.get_closest_marker("network") is not None
    if not network:
        request.getfixturevalue("isolated_home")
    credential_vars = (
        *(key.env_var for key in SUPPORTED_API_KEYS),
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_BASE_URL",
        "OPENCODE_API_KEY",
        "OPENAI_ADMIN_KEY",
        "OPENAI_BASE_URL",
        "AWS_BEDROCK_ACCESS_KEY_ID",
        "AWS_BEDROCK_SECRET_ACCESS_KEY",
        "AWS_BEDROCK_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_CONFIG_FILE",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        for env_var in () if network else credential_vars:
            monkeypatch.delenv(env_var, raising=False)
        # Never report test activity to a live Herdr pane.
        for env_var in ("HERDR_ENV", "HERDR_SOCKET_PATH", "HERDR_PANE_ID"):
            monkeypatch.delenv(env_var, raising=False)
        yield


@pytest.fixture
def isolated_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Isolate user files and config caches, then close session stores afterward."""

    fake_home = tmp_path_factory.mktemp("home")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setattr(config_module, "config_path", fake_home / ".klaude" / "klaude-config.yaml")
        monkeypatch.setattr(config_module, "example_config_path", fake_home / ".klaude" / "klaude-config.example.yaml")
        monkeypatch.setattr(auth_base, "KLAUDE_AUTH_FILE", fake_home / ".klaude" / "klaude-auth.json")
        monkeypatch.setattr(auth_env, "KLAUDE_AUTH_FILE", auth_base.KLAUDE_AUTH_FILE)
        load_config.cache_clear()

        try:
            yield fake_home
        finally:
            try:
                asyncio.run(close_default_store())
            finally:
                load_config.cache_clear()
