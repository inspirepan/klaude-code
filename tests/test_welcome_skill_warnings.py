import io

from rich.console import Console

from klaude_code.protocol import events
from klaude_code.protocol.llm_param import LLMClientProtocol, LLMConfigParameter
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.welcome import render_welcome


def test_render_welcome_shows_skill_warnings_section() -> None:
    llm_config = LLMConfigParameter(
        protocol=LLMClientProtocol.OPENAI,
        provider_name="demo",
        model_id="gpt-demo",
    )
    event = events.WelcomeEvent(
        session_id="s1",
        work_dir="/tmp",
        llm_config=llm_config,
        loaded_skill_warnings={"project": ["name mismatch"]},
    )

    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=120, theme=get_theme().app_theme)
    console.print(render_welcome(event))
    output = out.getvalue()

    assert "skill warnings" in output
    assert "name mismatch" in output
