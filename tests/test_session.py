# pyright: reportPrivateUsage=false
"""Tests for session module: export, selector, and session functionality."""

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from klaude_code.protocol import model
from klaude_code.protocol.llm_param import ToolSchema
from klaude_code.session import export
from klaude_code.session.session import Session

# =====================
# Tests for export.py
# =====================


class TestSanitizeFilename:
    """Tests for _sanitize_filename function."""

    def test_basic_text(self):
        result = export._sanitize_filename("hello world")
        assert result == "hello_world"

    def test_special_characters_removed(self):
        result = export._sanitize_filename("hello@world#test!")
        # Special characters are removed, no space between them so no underscore
        assert result == "helloworldtest"

    def test_chinese_characters_preserved(self):
        result = export._sanitize_filename("hello 你好 world")
        assert result == "hello_你好_world"

    def test_long_text_truncated(self):
        long_text = "a" * 100
        result = export._sanitize_filename(long_text)
        assert len(result) == export._MAX_FILENAME_MESSAGE_LEN
        assert result == "a" * 50

    def test_empty_returns_export(self):
        result = export._sanitize_filename("")
        assert result == "export"

    def test_only_special_chars_returns_export(self):
        result = export._sanitize_filename("!@#$%^&*()")
        assert result == "export"

    def test_multiple_spaces_collapsed(self):
        result = export._sanitize_filename("hello    world   test")
        assert result == "hello_world_test"


class TestEscapeHtml:
    """Tests for _escape_html function."""

    def test_basic_text_unchanged(self):
        assert export._escape_html("hello") == "hello"

    def test_angle_brackets_escaped(self):
        assert export._escape_html("<script>") == "&lt;script&gt;"

    def test_ampersand_escaped(self):
        assert export._escape_html("a & b") == "a &amp; b"

    def test_quotes_escaped(self):
        result = export._escape_html('say "hello"')
        assert result == "say &quot;hello&quot;"

    def test_single_quote_escaped(self):
        result = export._escape_html("it's")
        # html.escape uses &#x27; for single quotes
        assert result == "it&#x27;s"


class TestShortenPath:
    """Tests for _shorten_path function."""

    def test_home_path_shortened(self):
        home = str(Path.home())
        result = export._shorten_path(f"{home}/projects/test")
        assert result == "~/projects/test"

    def test_non_home_path_unchanged(self):
        result = export._shorten_path("/var/log/test")
        assert result == "/var/log/test"


class TestFormatTimestamp:
    """Tests for _format_timestamp function."""

    def test_valid_timestamp(self):
        ts = 1700000000.0  # 2023-11-14
        result = export._format_timestamp(ts)
        # Just check format, not exact value (timezone dependent)
        assert len(result) == 19  # "YYYY-MM-DD HH:MM:SS"
        assert "-" in result
        assert ":" in result

    def test_zero_timestamp_returns_now(self):
        result = export._format_timestamp(0)
        # Should return current time in proper format
        assert len(result) == 19

    def test_none_timestamp_returns_now(self):
        result = export._format_timestamp(None)
        assert len(result) == 19

    def test_negative_timestamp_returns_now(self):
        result = export._format_timestamp(-100)
        assert len(result) == 19


class TestFormatMsgTimestamp:
    """Tests for _format_msg_timestamp function."""

    def test_datetime_formatted(self):
        dt = datetime(2023, 11, 14, 10, 30, 45)
        result = export._format_msg_timestamp(dt)
        assert result == "2023-11-14 10:30:45"


class TestGetFirstUserMessage:
    """Tests for get_first_user_message function."""

    def test_finds_first_user_message(self):
        history: list[model.ConversationItem] = [
            model.AssistantMessageItem(content="Hello"),
            model.UserMessageItem(content="User message here"),
        ]
        result = export.get_first_user_message(history)
        assert result == "User message here"

    def test_empty_history_returns_export(self):
        result = export.get_first_user_message([])
        assert result == "export"

    def test_no_user_message_returns_export(self):
        history: list[model.ConversationItem] = [
            model.AssistantMessageItem(content="Hello"),
        ]
        result = export.get_first_user_message(history)
        assert result == "export"

    def test_truncates_long_first_line(self):
        long_message = "x" * 150
        history: list[model.ConversationItem] = [
            model.UserMessageItem(content=long_message),
        ]
        result = export.get_first_user_message(history)
        assert len(result) == 100

    def test_returns_only_first_line(self):
        history: list[model.ConversationItem] = [
            model.UserMessageItem(content="First line\nSecond line\nThird line"),
        ]
        result = export.get_first_user_message(history)
        assert result == "First line"

    def test_strips_whitespace(self):
        history: list[model.ConversationItem] = [
            model.UserMessageItem(content="  Hello world  "),
        ]
        result = export.get_first_user_message(history)
        assert result == "Hello world"


class TestFormatTokenCount:
    """Tests for _format_token_count function."""

    def test_small_number(self):
        assert export._format_token_count(500) == "500"
        assert export._format_token_count(999) == "999"

    def test_thousands(self):
        assert export._format_token_count(1000) == "1k"
        assert export._format_token_count(1500) == "1.5k"
        assert export._format_token_count(10000) == "10k"
        assert export._format_token_count(99500) == "99.5k"

    def test_millions(self):
        assert export._format_token_count(1000000) == "1M"
        assert export._format_token_count(1500000) == "1M500k"
        assert export._format_token_count(2000000) == "2M"


class TestFormatCost:
    """Tests for _format_cost function."""

    def test_usd_format(self):
        assert export._format_cost(0.0123, "USD") == "$0.0123"

    def test_cny_format(self):
        assert export._format_cost(0.5678, "CNY") == "¥0.5678"

    def test_default_is_usd(self):
        assert export._format_cost(1.0) == "$1.0000"


class TestShouldCollapse:
    """Tests for _should_collapse function."""

    def test_short_text_not_collapsed(self):
        assert export._should_collapse("short text") is False

    def test_many_lines_collapsed(self):
        text = "\n".join(["line"] * 101)
        assert export._should_collapse(text) is True

    def test_long_text_collapsed(self):
        text = "x" * 10001
        assert export._should_collapse(text) is True

    def test_exactly_at_threshold_not_collapsed(self):
        text = "\n".join(["line"] * 100)  # 100 lines
        assert export._should_collapse(text) is False


class TestBuildToolsHtml:
    """Tests for _build_tools_html function."""

    def test_empty_tools_returns_message(self):
        result = export._build_tools_html([])
        assert "No tools registered" in result

    def test_tool_with_name_and_description(self):
        tools = [
            ToolSchema(
                name="TestTool",
                type="function",
                description="A test tool",
                parameters={},
            )
        ]
        result = export._build_tools_html(tools)
        assert "TestTool" in result
        assert "A test tool" in result


class TestBuildToolParamsHtml:
    """Tests for _build_tool_params_html function."""

    def test_empty_params(self):
        result = export._build_tool_params_html({})
        assert result == ""

    def test_no_properties(self):
        result = export._build_tool_params_html({"type": "object"})
        assert result == ""

    def test_params_with_required(self):
        params: dict[str, object] = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The name"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        result = export._build_tool_params_html(params)
        assert "name" in result
        assert "string" in result
        assert "The name" in result
        assert "(required)" in result

    def test_params_with_union_type(self):
        params: dict[str, object] = {
            "type": "object",
            "properties": {
                "value": {"type": ["string", "null"]},
            },
        }
        result = export._build_tool_params_html(params)
        assert "string | null" in result


class TestTryRenderTodoArgs:
    """Tests for _try_render_todo_args function."""

    def test_valid_todos(self):
        args = json.dumps(
            {
                "todos": [
                    {"content": "Task 1", "status": "pending"},
                    {"content": "Task 2", "status": "completed"},
                ]
            }
        )
        result = export._try_render_todo_args(args)
        assert result is not None
        assert "Task 1" in result
        assert "Task 2" in result
        assert "status-pending" in result
        assert "status-completed" in result

    def test_invalid_json(self):
        result = export._try_render_todo_args("not json")
        assert result is None

    def test_missing_todos_key(self):
        result = export._try_render_todo_args('{"other": []}')
        assert result is None

    def test_empty_todos_list(self):
        result = export._try_render_todo_args('{"todos": []}')
        assert result is None


class TestGetDiffText:
    """Tests for _get_diff_text function."""

    def test_diff_text_ui_extra(self):
        extra = model.DiffTextUIExtra(diff_text="+added line")
        result = export._get_diff_text(extra)
        assert result == "+added line"

    def test_none_returns_none(self):
        assert export._get_diff_text(None) is None

    def test_other_type_returns_none(self):
        extra = model.MermaidLinkUIExtra(link="http://example.com", line_count=10)
        result = export._get_diff_text(extra)
        assert result is None


class TestRenderDiffBlock:
    """Tests for _render_diff_block function."""

    def test_plus_lines_styled(self):
        diff = "+added line"
        result = export._render_diff_block(diff)
        assert "diff-plus" in result
        assert "added line" in result

    def test_minus_lines_styled(self):
        diff = "-removed line"
        result = export._render_diff_block(diff)
        assert "diff-minus" in result
        assert "removed line" in result

    def test_context_lines_styled(self):
        diff = " context line"
        result = export._render_diff_block(diff)
        assert "diff-ctx" in result


class TestRenderTextBlock:
    """Tests for _render_text_block function."""

    def test_short_text_not_expandable(self):
        text = "short text"
        result = export._render_text_block(text)
        assert "expandable" not in result
        assert "short text" in result

    def test_long_text_expandable(self):
        # More than _TOOL_OUTPUT_PREVIEW_LINES lines
        lines = [f"line {i}" for i in range(20)]
        text = "\n".join(lines)
        result = export._render_text_block(text)
        assert "expandable" in result
        assert "click to expand" in result


# =====================
# Tests for session.py
# =====================


class TestSession:
    """Tests for Session class."""

    def test_create_session_with_defaults(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        assert session.id is not None
        assert len(session.id) == 32  # UUID hex format
        assert session.work_dir == tmp_path
        assert session.conversation_history == []
        assert session.todos == []
        assert session.model_name is None

    def test_messages_count_empty(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        assert session.messages_count == 0

    def test_messages_count_with_history(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        session.conversation_history = [
            model.UserMessageItem(content="Hello"),
            model.AssistantMessageItem(content="Hi"),
            model.ToolCallItem(call_id="1", name="test", arguments="{}"),
            model.UserMessageItem(content="Bye"),
        ]
        # Should count only User and Assistant messages
        assert session.messages_count == 3

    def test_messages_count_cached(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        session.conversation_history = [
            model.UserMessageItem(content="Hello"),
            model.AssistantMessageItem(content="Hi"),
        ]
        # First access calculates and caches
        count1 = session.messages_count
        assert count1 == 2
        # Second access should use cache
        count2 = session.messages_count
        assert count2 == 2

    def test_invalidate_messages_count_cache(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        session.conversation_history = [
            model.UserMessageItem(content="Hello"),
        ]
        assert session.messages_count == 1
        session._invalidate_messages_count_cache()
        # Add more messages manually
        session.conversation_history.append(model.UserMessageItem(content="World"))
        assert session.messages_count == 2


class TestSessionProjectKey:
    """Tests for Session._project_key method."""

    def test_project_key_format(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        key = Session._project_key()
        # Should be path with slashes replaced by dashes, leading slash stripped
        assert "/" not in key
        assert key != ""


class TestSessionDirectories:
    """Tests for Session directory methods."""

    def test_base_dir_under_home(self):
        base = Session._base_dir()
        # _base_dir() returns ~/.klaude/projects/<project_key>
        # So parent should be ~/.klaude/projects
        assert base.parent == Path.home() / ".klaude" / "projects"

    def test_sessions_dir_under_base(self):
        sessions_dir = Session._sessions_dir()
        assert sessions_dir.name == "sessions"

    def test_messages_dir_under_base(self):
        messages_dir = Session._messages_dir()
        assert messages_dir.name == "messages"

    def test_exports_dir_under_base(self):
        exports_dir = Session._exports_dir()
        assert exports_dir.name == "exports"


class TestSessionNeedTurnStart:
    """Tests for Session.need_turn_start method."""

    def test_turn_start_for_assistant_after_user(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        prev = model.UserMessageItem(content="Hi")
        item = model.AssistantMessageItem(content="Hello")
        assert session.need_turn_start(prev, item) is True

    def test_turn_start_for_reasoning_after_tool_result(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        prev = model.ToolResultItem(call_id="1", output="done", status="success")
        item = model.ReasoningTextItem(content="Thinking...")
        assert session.need_turn_start(prev, item) is True

    def test_no_turn_start_for_user_message(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        prev = model.AssistantMessageItem(content="Hello")
        item = model.UserMessageItem(content="Hi")
        assert session.need_turn_start(prev, item) is False

    def test_turn_start_when_prev_none(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        item = model.AssistantMessageItem(content="Hello")
        assert session.need_turn_start(None, item) is True

    def test_no_turn_start_for_consecutive_assistant(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        prev = model.AssistantMessageItem(content="Hello")
        item = model.ToolCallItem(call_id="1", name="test", arguments="{}")
        assert session.need_turn_start(prev, item) is False


class TestSessionPersistence:
    """Tests for Session save/load with file system."""

    def test_save_and_load_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Create a unique project directory
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        # Create session with some data
        session = Session(work_dir=project_dir, model_name="test-model")
        session.todos = [model.TodoItem(content="Task 1", status="pending")]
        session.file_tracker = {"/path/to/file": 1234567890.0}
        session.save()

        # Load the session
        loaded = Session.load(session.id)
        assert loaded.id == session.id
        assert loaded.work_dir == project_dir
        assert loaded.model_name == "test-model"
        assert len(loaded.todos) == 1
        assert loaded.todos[0].content == "Task 1"
        assert "/path/to/file" in loaded.file_tracker

    def test_load_nonexistent_session_creates_new(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        # Load a session that doesn't exist
        loaded = Session.load("nonexistent123")
        assert loaded.id == "nonexistent123"
        assert loaded.work_dir == Path.cwd()

    def test_append_history(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        session = Session(work_dir=project_dir)
        items = [
            model.UserMessageItem(content="Hello"),
            model.AssistantMessageItem(content="Hi there"),
        ]
        session.append_history(items)

        assert len(session.conversation_history) == 2
        assert session.messages_count == 2

        # Verify the messages file was created
        messages_file = session._messages_file()
        assert messages_file.exists()

        # Load and verify
        loaded = Session.load(session.id)
        assert len(loaded.conversation_history) == 2


class TestSessionListAndClean:
    """Tests for Session.list_sessions and clean methods."""

    def test_list_sessions_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        sessions = Session.list_sessions()
        assert sessions == []

    def test_list_sessions_returns_metadata(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        # Create a session
        session = Session(work_dir=project_dir, model_name="gpt-4")
        session.append_history([model.UserMessageItem(content="Test message")])

        sessions = Session.list_sessions()
        assert len(sessions) == 1
        meta = sessions[0]
        assert meta.id == session.id
        assert meta.model_name == "gpt-4"
        assert meta.first_user_message == "Test message"
        assert meta.messages_count == 1

    def test_list_sessions_sorted_by_updated_at(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        # Create two sessions with different timestamps
        session1 = Session(work_dir=project_dir)
        session1.created_at = time.time() - 100
        session1.append_history([model.UserMessageItem(content="First")])

        session2 = Session(work_dir=project_dir)
        session2.created_at = time.time()
        session2.append_history([model.UserMessageItem(content="Second")])

        sessions = Session.list_sessions()
        assert len(sessions) == 2
        # Most recent first
        assert sessions[0].id == session2.id
        assert sessions[1].id == session1.id

    def test_most_recent_session_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        # No sessions yet
        assert Session.most_recent_session_id() is None

        # Create a session
        session = Session(work_dir=project_dir)
        session.save()

        assert Session.most_recent_session_id() == session.id

    def test_clean_small_sessions(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        # Create a small session (less than 5 messages)
        small_session = Session(work_dir=project_dir)
        small_session.append_history([model.UserMessageItem(content="Only one")])

        # Create a larger session (5+ messages)
        large_session = Session(work_dir=project_dir)
        large_session.append_history(
            [
                model.UserMessageItem(content="1"),
                model.AssistantMessageItem(content="2"),
                model.UserMessageItem(content="3"),
                model.AssistantMessageItem(content="4"),
                model.UserMessageItem(content="5"),
            ]
        )

        # Should have 2 sessions
        assert len(Session.list_sessions()) == 2

        # Clean small sessions
        deleted = Session.clean_small_sessions(min_messages=5)
        assert deleted == 1

        # Should have 1 session left
        sessions = Session.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].id == large_session.id

    def test_clean_all_sessions(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        # Create some sessions
        for i in range(3):
            session = Session(work_dir=project_dir)
            session.append_history([model.UserMessageItem(content=f"Message {i}")])

        assert len(Session.list_sessions()) == 3

        deleted = Session.clean_all_sessions()
        assert deleted == 3
        assert len(Session.list_sessions()) == 0


class TestSessionMetaBrief:
    """Tests for Session.SessionMetaBrief model."""

    def test_create_meta_brief(self):
        meta = Session.SessionMetaBrief(
            id="test123",
            created_at=1700000000.0,
            updated_at=1700001000.0,
            work_dir="/home/user/project",
            path="/home/user/.klaude/projects/test/sessions/test123.json",
            first_user_message="Hello world",
            messages_count=5,
            model_name="gpt-4",
        )
        assert meta.id == "test123"
        assert meta.first_user_message == "Hello world"
        assert meta.messages_count == 5

    def test_default_values(self):
        meta = Session.SessionMetaBrief(
            id="test",
            created_at=0.0,
            updated_at=0.0,
            work_dir="",
            path="",
        )
        assert meta.first_user_message is None
        assert meta.messages_count == -1
        assert meta.model_name is None


class TestRenderMetadata:
    """Tests for metadata rendering functions."""

    def test_render_single_metadata_basic(self):
        metadata = model.TaskMetadata(
            model_name="gpt-4",
            provider="OpenAI",
            usage=model.Usage(
                input_tokens=100,
                output_tokens=50,
            ),
            task_duration_s=2.5,
        )
        result = export._render_single_metadata(metadata)
        assert "gpt-4" in result
        assert "openai" in result.lower()
        assert "input:" in result
        assert "output:" in result
        assert "time:" in result

    def test_render_single_metadata_with_cost(self):
        metadata = model.TaskMetadata(
            model_name="claude-3",
            usage=model.Usage(
                input_tokens=1000,
                output_tokens=500,
                input_cost=0.01,
                output_cost=0.05,
            ),
        )
        result = export._render_single_metadata(metadata)
        assert "$" in result
        assert "cost:" in result

    def test_render_metadata_item_with_subagents(self):
        main = model.TaskMetadata(
            model_name="gpt-4",
            usage=model.Usage(input_tokens=100, output_tokens=50),
        )
        sub = model.TaskMetadata(
            model_name="gpt-3.5",
            usage=model.Usage(input_tokens=50, output_tokens=25),
        )
        item = model.TaskMetadataItem(main=main, sub_agent_task_metadata=[sub])
        result = export._render_metadata_item(item)
        assert "gpt-4" in result
        assert "gpt-3.5" in result
