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
        loaded_skill_warnings={"project": ["name mismatch", "another warning"]},
    )

    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=120, theme=get_theme().app_theme)
    console.print(render_welcome(event))
    output = out.getvalue()

    assert "skill warnings" in output
    assert "name mismatch" in output
    assert "another warning" in output
    # Each warning should be on its own line, not joined with " | "
    assert " | " not in output

def test_render_welcome_merges_memories_and_skills_into_context_tree() -> None:
    llm_config = LLMConfigParameter(
        protocol=LLMClientProtocol.OPENAI,
        provider_name="demo",
        model_id="gpt-demo",
    )
    event = events.WelcomeEvent(
        session_id="s1",
        work_dir="/tmp",
        llm_config=llm_config,
        loaded_memories={"user": ["/tmp/user.md"], "project": ["/work/project.md"]},
        loaded_skills={"system": ["playwright", "web-search"]},
    )

    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=120, theme=get_theme().app_theme)
    console.print(render_welcome(event))
    output = out.getvalue()

    assert "context" in output
    assert "user memory" in output
    assert "project memory" in output
    assert "system skills" in output
    assert "skills" not in output.split("context", 1)[0]
    assert "user.md" in output
    assert "/work/project.md" in output
    assert "playwright" in output
    assert "web-search" in output
    assert "── playwright" not in output

def test_render_welcome_keeps_per_group_multi_column_layout() -> None:
    llm_config = LLMConfigParameter(
        protocol=LLMClientProtocol.OPENAI,
        provider_name="demo",
        model_id="gpt-demo",
    )
    event = events.WelcomeEvent(
        session_id="s1",
        work_dir="/tmp",
        llm_config=llm_config,
        loaded_memories={
            "user": ["/very/long/path/to/a/memory/file/that/should/not/force/skills/to_single_column/user-memory.md"]
        },
        loaded_skills={"system": ["playwright", "web-search", "render-mermaid", "commit"]},
    )

    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=120, theme=get_theme().app_theme)
    console.print(render_welcome(event))
    output = out.getvalue()

    assert "system skills" in output
    assert "playwright | web-search" in output or "web-search | render-mermaid" in output

def test_render_welcome_shows_startup_update_and_shortcuts() -> None:
    llm_config = LLMConfigParameter(
        protocol=LLMClientProtocol.OPENAI,
        provider_name="demo",
        model_id="gpt-demo",
    )
    event = events.WelcomeEvent(
        session_id="s1",
        work_dir="/tmp",
        llm_config=llm_config,
        startup_info=events.WelcomeStartupInfo(
            update_info=events.WelcomeUpdateInfo(
                message="PyPI 9.9.9 available. Current 1.0.0 (PyPI install); run `klaude upgrade`.",
            )
        ),
    )

    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=120, theme=get_theme().app_theme)
    console.print(render_welcome(event))
    output = out.getvalue()

    assert "update" in output
    assert "PyPI 9.9.9 available." in output
    assert "shortcuts" in output
    assert "├── @ files" in output
    assert "├── // skills" in output
    assert "change model (this chat)" in output
    assert "change thinking level" in output
    assert "paste image" in output
    assert "├──" in output

def test_render_welcome_hides_startup_shortcuts_without_startup_info() -> None:
    llm_config = LLMConfigParameter(
        protocol=LLMClientProtocol.OPENAI,
        provider_name="demo",
        model_id="gpt-demo",
    )
    event = events.WelcomeEvent(
        session_id="s1",
        work_dir="/tmp",
        llm_config=llm_config,
    )

    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=120, theme=get_theme().app_theme)
    console.print(render_welcome(event))
    output = out.getvalue()

    assert "shortcuts" not in output
