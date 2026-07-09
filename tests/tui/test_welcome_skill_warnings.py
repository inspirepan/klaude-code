import io
from pathlib import Path

from rich.console import Console

from klaude_code.protocol import events
from klaude_code.protocol.llm_param import LLMClientProtocol, LLMConfigParameter
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.welcome import render_welcome


def _print_welcome(event: events.WelcomeEvent) -> str:
    out = io.StringIO()
    console = Console(file=out, force_terminal=False, width=200, theme=get_theme().app_theme)
    console.print(render_welcome(event))
    return out.getvalue()


def test_render_welcome_shows_skill_warnings_section() -> None:
    llm_config = LLMConfigParameter(
        protocol=LLMClientProtocol.OPENAI,
        provider_name="demo",
        model_id="gpt-demo",
    )
    event = events.WelcomeEvent(
        session_id="s1",
        work_dir="/tmp/project",
        llm_config=llm_config,
        loaded_skill_warnings={
            "project": [
                'skill name "youtube-draft" should match directory name "pi-youtube-draft":\n'
                "- [project] /tmp/project/.claude/skills/pi-youtube-draft/SKILL.md",
                "another warning",
            ]
        },
    )

    output = _print_welcome(event)

    assert "skill warnings" in output
    assert "youtube-draft ≠ pi-youtube-draft  [project] .claude/skills/pi-youtube-draft" in output
    assert "another warning" in output
    assert 'skill name "' not in output
    assert "should match directory name" not in output
    assert "SKILL.md" not in output


def test_render_welcome_shows_duplicate_skill_warning_as_single_line_chain() -> None:
    system_path = Path.home() / ".klaude/skills/.system/pdf/SKILL.md"
    project_path = Path("/tmp/project/.claude/skills/pdf/SKILL.md")
    llm_config = LLMConfigParameter(
        protocol=LLMClientProtocol.OPENAI,
        provider_name="demo",
        model_id="gpt-demo",
    )
    event = events.WelcomeEvent(
        session_id="s1",
        work_dir="/tmp/project",
        llm_config=llm_config,
        loaded_skill_warnings={
            "project": [f'duplicate "pdf" skill:\n- [system] {system_path}\n- [project] {project_path} (using this)']
        },
    )

    output = _print_welcome(event)

    assert "pdf  [system] ~/.klaude/skills/.system/pdf → [project] .claude/skills/pdf" in output
    assert 'duplicate "' not in output
    assert "(using this)" not in output
    assert "SKILL.md" not in output
    assert "  • [system]" not in output


def test_render_welcome_merges_same_name_duplicate_warnings_into_one_chain() -> None:
    system_path = Path.home() / ".klaude/skills/.system/gpt-image-gen/SKILL.md"
    user_path = Path.home() / ".claude/skills/gpt-image-gen/SKILL.md"
    project_path = Path("/tmp/project/.claude/skills/gpt-image-gen/SKILL.md")
    llm_config = LLMConfigParameter(
        protocol=LLMClientProtocol.OPENAI,
        provider_name="demo",
        model_id="gpt-demo",
    )
    event = events.WelcomeEvent(
        session_id="s1",
        work_dir="/tmp/project",
        llm_config=llm_config,
        loaded_skill_warnings={
            "user": [f'duplicate "gpt-image-gen" skill:\n- [system] {system_path}\n- [user] {user_path} (using this)'],
            "project": [
                f'duplicate "gpt-image-gen" skill:\n- [user] {user_path}\n- [project] {project_path} (using this)'
            ],
        },
    )

    output = _print_welcome(event)

    assert (
        "gpt-image-gen  [system] ~/.klaude/skills/.system/gpt-image-gen"
        " → [user] ~/.claude/skills/gpt-image-gen"
        " → [project] .claude/skills/gpt-image-gen"
    ) in output
    # Merged into a single tree leaf
    assert output.count("gpt-image-gen  [system]") == 1


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

    output = _print_welcome(event)

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

    output = _print_welcome(event)

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

    output = _print_welcome(event)

    assert "update" in output
    assert "PyPI 9.9.9 available." in output
    assert "shortcuts" in output
    assert "├── @ files · / commands · // skills · ! shell" in output
    assert "change model (this chat)" in output
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

    output = _print_welcome(event)

    assert "shortcuts" not in output
