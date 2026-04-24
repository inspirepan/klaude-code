# Test Guidelines

## Always Use `isolated_home` When a Test May Touch the Session Store

Any test that constructs a `Session`, invokes code that writes to `~/.klaude`
(session history, auth cache, config overrides, skill install dir, etc.), or
exercises anything that calls `Path.home()` **must** depend on the
`isolated_home` fixture from `tests/conftest.py`.

Without it, tests will write into the developer's real `~/.klaude` directory
and leave behind persisted sessions, half-flushed history files, and stale
store state across runs.

### What `isolated_home` does

Defined in `tests/conftest.py`:

- Redirects `$HOME` and `Path.home()` to a per-test temp directory via
  `monkeypatch`.
- After the test, calls `close_default_store()` so background session flush
  connections are closed cleanly.

### How to use it

Add `isolated_home: Path` to the test signature. If the test doesn't need the
path itself, use `del isolated_home` (or pass it to an inner async helper) so
type checkers / linters stop complaining about the unused parameter.

```python
from pathlib import Path

import pytest

from klaude_code.session.session import Session


def test_something_that_touches_session(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home  # fixture only needed for its side effects

    session = Session(work_dir=tmp_path)
    ...
```

For `async` tests driven via `asyncio.run(_test())`, put the fixture on the
outer sync function — the patching happens before the event loop starts, so
everything inside the coroutine still sees the redirected `HOME`.

### When you MUST use it

- Instantiating `Session(...)` (even with `work_dir=tmp_path`, because the
  store path is derived from `Path.home()`).
- Calling anything that ends up in `session.flush()` / session persistence.
- Code paths that read/write auth credentials, user config, or skill install
  state under `~/.klaude` or `~/.config`.
- Tests that spin up the agent runtime (`AgentOperationHandler`, handoff,
  rewind, compaction, title refresh, away summary, etc.).

### When you don't need it

- Pure unit tests that only touch in-memory structures (reducers, parsers,
  small helpers).
- Tests that already fully patch out `Path.home()` / the store themselves.

When in doubt, add `isolated_home`. It's cheap and prevents flaky,
developer-machine-specific failures.

## Other Conventions

- Test files live under `tests/<area>/test_*.py` mirroring the source layout.
- Run a single file quickly with
  `uv run pytest tests/<area>/test_foo.py -x -q --tb=short`.
- Prefer `tmp_path` for scratch filesystem state and `monkeypatch` over
  manual `os.environ` mutation.
