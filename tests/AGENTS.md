# Test Guidelines

## Ordinary Tests Automatically Isolate User State and Credentials

The autouse `isolate_local_credentials` fixture enables `isolated_home` for
every test without a `network` marker and removes inherited provider credential
environment variables. Tests must supply their own fake credentials or patch
client factories; never rely on a developer's API keys or OAuth login.

Tests marked `network` retain the real environment. Keep external-service tests
behind this marker; `make test` excludes them.

## Use `isolated_home` Explicitly When You Need Its Path

Add an explicit dependency when the test needs the isolated directory or when a
network test must isolate user files too. Ordinary tests that construct a
`Session` or read config/auth files need no explicit dependency for isolation.

### What `isolated_home` does

Defined in `tests/conftest.py`:

- Redirects `$HOME` and `Path.home()` to a per-test temp directory via
  `monkeypatch`.
- Redirects the config and auth file paths captured at module import time.
- Clears the loaded config cache before and after each test.
- After the test, calls `close_default_store()` so background session flush
  connections are closed cleanly.

### How to use it

Use the fixture's returned path rather than assuming its directory name:

```python
from pathlib import Path

def test_something_that_reads_user_files(isolated_home: Path) -> None:
    user_dir = isolated_home / ".klaude"
    ...
```

For tests driven via `asyncio.run(_test())`, fixture setup occurs before the
event loop starts, so the coroutine also sees the isolated environment.

## Other Conventions

- Test files live under `tests/<area>/test_*.py` mirroring the source layout.
- Run a single file quickly with
  `uv run pytest tests/<area>/test_foo.py -x -q --tb=short`.
- Prefer `tmp_path` for scratch filesystem state and `monkeypatch` over
  manual `os.environ` mutation.
