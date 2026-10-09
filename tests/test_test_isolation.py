from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


def test_unit_tests_ignore_local_credentials_but_network_tests_keep_them(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_home = tmp_path / "developer-home"
    user_dir = original_home / ".klaude"
    user_dir.mkdir(parents=True)
    config_file = user_dir / "klaude-config.yaml"
    config_file.write_text("invalid: [")
    auth_file = user_dir / "klaude-auth.json"
    auth_file.write_text('{"env": {"OPENAI_API_KEY": "stored-test-key"}}')
    monkeypatch.setenv("HOME", str(original_home))
    monkeypatch.setenv("TEST_ORIGINAL_HOME", str(original_home))
    for name in ("OPENAI_API_KEY", "AWS_ACCESS_KEY_ID", "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.setenv(name, "inherited-test-value")

    pytester.makeconftest((Path(__file__).parent / "conftest.py").read_text())
    pytester.makeini("[pytest]\nmarkers = network: requires real environment\n")
    pytester.makepyfile(
        """
        import os
        from pathlib import Path
        import pytest
        from klaude_code.auth import base, env
        from klaude_code.config import config as schema
        from klaude_code.config.loader import load_config

        def test_unit_environment(tmp_path):
            assert list(tmp_path.iterdir()) == []
            assert Path.home() != Path(os.environ["TEST_ORIGINAL_HOME"])
            assert Path(os.environ["HOME"]) == Path.home()
            for name in ("OPENAI_API_KEY", "AWS_ACCESS_KEY_ID", "GOOGLE_APPLICATION_CREDENTIALS"):
                assert name not in os.environ
            assert schema.config_path.parent.parent == Path.home()
            assert schema.example_config_path.parent.parent == Path.home()
            assert base.KLAUDE_AUTH_FILE == env.KLAUDE_AUTH_FILE
            assert env.KLAUDE_AUTH_FILE.parent.parent == Path.home()
            assert env.get_auth_env("OPENAI_API_KEY") is None
            config = load_config()
            assert not config.iter_model_entries(only_available=True)
            config.main_model = "cached-from-another-test"
            env.set_auth_env("OPENAI_API_KEY", "another-test-key")

        def test_next_unit_environment():
            assert load_config().main_model != "cached-from-another-test"
            assert env.get_auth_env("OPENAI_API_KEY") is None

        @pytest.mark.network
        def test_network_environment():
            assert Path.home() == Path(os.environ["TEST_ORIGINAL_HOME"])
            for name in ("OPENAI_API_KEY", "AWS_ACCESS_KEY_ID", "GOOGLE_APPLICATION_CREDENTIALS"):
                assert os.environ[name] == "inherited-test-value"
            assert env.get_auth_env("OPENAI_API_KEY") == "stored-test-key"
        """
    )

    result = pytester.runpytest_subprocess("-q")

    result.assert_outcomes(passed=3)
    assert config_file.read_text() == "invalid: ["
    assert auth_file.read_text() == '{"env": {"OPENAI_API_KEY": "stored-test-key"}}'
