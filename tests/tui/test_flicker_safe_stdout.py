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


def test_settle_flicker_safe_stdout_returns_when_no_pending_work() -> None:
    """When there are no buffered writes, settle returns promptly. This is
    the common case at the runner sync points and must not hang."""
    from klaude_code.tui.input.flicker_safe_stdout import (
        FlickerSafeStdoutProxy,
        settle_flicker_safe_stdout,
    )

    proxy = FlickerSafeStdoutProxy(sleep_between_writes=0.5, raw=True)

    async def _scenario() -> None:
        # Without a patched sys.stdout, settle is a no-op.
        await settle_flicker_safe_stdout()

        # Even with the proxy installed, an empty queue + no in-flight
        # futures returns straight away.
        try:
            import sys

            original = sys.stdout
            sys.stdout = proxy  # type: ignore[assignment]
            try:
                await settle_flicker_safe_stdout(timeout=0.5)
            finally:
                sys.stdout = original
        finally:
            proxy.close()

    asyncio.run(_scenario())


def test_wait_for_pending_writes_drains_in_flight_futures() -> None:
    """When in-flight in_terminal futures exist, wait_for_pending_writes
    awaits them. We simulate this by putting a completed future into the
    pending set; the wait should resolve."""
    from klaude_code.tui.input.flicker_safe_stdout import FlickerSafeStdoutProxy

    proxy = FlickerSafeStdoutProxy(sleep_between_writes=0.5, raw=True)

    async def _scenario() -> None:
        loop = asyncio.get_event_loop()
        future: asyncio.Future[None] = loop.create_future()
        proxy._pending_in_terminal.add(future)

        async def _resolve_after_yield() -> None:
            await asyncio.sleep(0)
            if not future.done():
                future.set_result(None)

        loop.create_task(_resolve_after_yield())
        await proxy.wait_for_pending_writes(timeout=1.0)
        assert future.done()

    try:
        asyncio.run(_scenario())
    finally:
        proxy.close()
