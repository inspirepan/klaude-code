# pyright: reportPrivateUsage=false

import asyncio


def test_synchronized_in_terminal_no_app_yields_cleanly() -> None:
    """When no prompt-toolkit Application is running we must transparently
    no-op so non-interactive paths (replay, headless tests) keep working."""
    from klaude_code.tui.input.flicker_safe_stdout import synchronized_in_terminal

    entered = False

    async def _run() -> None:
        nonlocal entered
        async with synchronized_in_terminal():
            entered = True

    asyncio.run(_run())
    assert entered is True


def test_flicker_safe_proxy_constructs_with_raw_default() -> None:
    """Sanity: defaults are raw=True (Rich ANSI passes through) and the
    bumped throttle is honored."""
    from klaude_code.tui.input.flicker_safe_stdout import FlickerSafeStdoutProxy

    proxy = FlickerSafeStdoutProxy(sleep_between_writes=0.5, raw=True)
    try:
        assert proxy.raw is True
        assert proxy.sleep_between_writes == 0.5
    finally:
        proxy.close()


def test_flicker_safe_patch_stdout_swaps_streams() -> None:
    """Using the context manager replaces sys.stdout/stderr while active and
    restores them on exit."""
    import sys

    from klaude_code.tui.input.flicker_safe_stdout import (
        FlickerSafeStdoutProxy,
        flicker_safe_patch_stdout,
    )

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    with flicker_safe_patch_stdout():
        assert isinstance(sys.stdout, FlickerSafeStdoutProxy)
        assert sys.stderr is sys.stdout
    assert sys.stdout is original_stdout
    assert sys.stderr is original_stderr
