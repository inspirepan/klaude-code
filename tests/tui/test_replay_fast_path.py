# pyright: reportPrivateUsage=false

import asyncio
import io

from rich.console import Console


def test_replay_mode_defers_assistant_stream_until_end() -> None:
    from klaude_code.tui.commands import AppendAssistant, EndAssistantStream, StartAssistantStream
    from klaude_code.tui.renderer import TUICommandRenderer

    stream_updates: list[tuple[str, ...]] = []

    def _sink(lines: tuple[str, ...], _end_of_stream: bool) -> None:
        stream_updates.append(lines)

    renderer = TUICommandRenderer(stream_sink=_sink)

    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    renderer.console.push_theme(renderer.themes.markdown_theme)

    renderer.set_replay_mode(True)

    session_id = "replay-session"

    asyncio.run(renderer.execute([StartAssistantStream(session_id=session_id)]))
    assert output.getvalue() == ""
    assert stream_updates == []

    asyncio.run(renderer.execute([AppendAssistant(session_id=session_id, content="First paragraph.\n\n")]))
    assert output.getvalue() == ""
    assert stream_updates == []

    asyncio.run(renderer.execute([AppendAssistant(session_id=session_id, content="Second paragraph.\n")]))
    assert output.getvalue() == ""
    assert stream_updates == []

    asyncio.run(renderer.execute([EndAssistantStream(session_id=session_id)]))

    rendered = output.getvalue()
    assert "First paragraph." in rendered
    assert "Second paragraph." in rendered
