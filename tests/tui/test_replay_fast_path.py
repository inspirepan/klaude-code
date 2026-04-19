# pyright: reportPrivateUsage=false

import asyncio
import io

from rich.console import Console


def test_replay_mode_does_not_start_bottom_live_for_assistant_stream() -> None:
    from klaude_code.tui.commands import AppendAssistant, EndAssistantStream, StartAssistantStream
    from klaude_code.tui.renderer import TUICommandRenderer

    renderer = TUICommandRenderer()

    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    renderer.console.push_theme(renderer.themes.markdown_theme)

    renderer.set_replay_mode(True)

    session_id = "replay-session"

    asyncio.run(renderer.execute([StartAssistantStream(session_id=session_id)]))
    assert renderer._bottom_live is None
    assert output.getvalue() == ""

    asyncio.run(renderer.execute([AppendAssistant(session_id=session_id, content="First paragraph.\n\n")]))
    assert renderer._bottom_live is None
    assert output.getvalue() == ""

    asyncio.run(renderer.execute([AppendAssistant(session_id=session_id, content="Second paragraph.\n")]))
    assert renderer._bottom_live is None
    assert output.getvalue() == ""

    asyncio.run(renderer.execute([EndAssistantStream(session_id=session_id)]))
    assert renderer._bottom_live is None

    rendered = output.getvalue()
    assert "First paragraph." in rendered
    assert "Second paragraph." in rendered
