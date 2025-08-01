import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from klaudecode.config import ConfigValue
from klaudecode.message import UserMessage
from klaudecode.user_command.command_debug import DebugCommand
from klaudecode.user_input import UserInput


class MockMessage:
    """Mock message for testing"""

    def __init__(self, role: str, content: str = "test content", removed: bool = False):
        self.role = role
        self.content = content
        self.removed = removed

    def __bool__(self):
        return not self.removed

    def to_openai(self):
        return {"role": self.role, "content": self.content}

    def to_anthropic(self):
        if self.role == "system":
            return {"type": "text", "text": self.content}
        return {"role": self.role, "content": self.content}


class MockSystemMessage(MockMessage):
    """Mock SystemMessage for testing"""

    def __init__(self, content: str = "System prompt", removed: bool = False):
        super().__init__("system", content, removed)

    def to_anthropic(self):
        return {"type": "text", "text": self.content}


class MockTool:
    """Mock tool for testing"""

    def __init__(self, name: str):
        self.name = name
        self.description = f"Mock tool {name}"

    def openai_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def anthropic_schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {"type": "object", "properties": {}},
        }


class TestDebugCommand:
    """Test cases for DebugCommand"""

    def setup_method(self):
        """Set up test environment"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.debug_command = DebugCommand()

        # Create mock agent state
        self.mock_agent_state = Mock()
        self.mock_agent_state.session = Mock()
        self.mock_agent_state.session.work_dir = self.temp_path

        # Create mock messages
        self.mock_messages = [
            MockMessage("user", "Hello"),
            MockMessage("assistant", "Hi there"),
            MockMessage("tool", "Tool result"),
            MockMessage(
                "user", "Another message", removed=True
            ),  # This should be filtered out
        ]

        self.mock_agent_state.session.messages = Mock()
        self.mock_agent_state.session.messages.messages = self.mock_messages

        # Create mock tools
        self.mock_tools = [MockTool("read"), MockTool("write"), MockTool("grep")]
        self.mock_agent_state.all_tools = self.mock_tools

        # Create mock config
        self.mock_config = Mock()
        self.mock_config.base_url = ConfigValue("https://api.openai.com/v1/", "test")
        self.mock_config.model_name = ConfigValue("gpt-4", "test")
        self.mock_config.api_key = ConfigValue("test-key-123", "test")
        self.mock_config.max_tokens = ConfigValue(4000, "test")
        self.mock_agent_state.config = self.mock_config

    def teardown_method(self):
        """Clean up test environment"""
        self.temp_dir.cleanup()

    def test_get_name(self):
        """Test command name"""
        assert self.debug_command.get_name() == "debug"

    def test_get_command_desc(self):
        """Test command description"""
        desc = self.debug_command.get_command_desc()
        assert "OpenAI/Anthropic" in desc
        assert "API schema" in desc
        assert "debugging" in desc

    @pytest.mark.asyncio
    async def test_export_openai_schema(self):
        """Test OpenAI schema export"""
        # Mock user_select to return OpenAI option (index 1)
        # Mock subprocess.run to prevent actual file opening
        with pytest.MonkeyPatch().context() as m:
            m.setattr(
                "klaudecode.user_command.command_debug.user_select",
                AsyncMock(return_value=1),
            )
            m.setattr("klaudecode.user_command.command_debug.subprocess.run", Mock())

            user_input = UserInput(
                command_name="debug", cleaned_input="/debug", raw_input="/debug"
            )
            command_output = await self.debug_command.handle(
                self.mock_agent_state, user_input
            )

            # Check that user message is removed
            assert command_output.user_msg.removed is True

            # Check export data
            debug_info = command_output.user_msg.get_extra_data("debug_exported")
            assert debug_info is not None
            assert debug_info["type"] == "schema"
            assert debug_info["provider"] == "openai"
            assert debug_info["message_count"] == 3  # 4 messages - 1 removed
            assert debug_info["tool_count"] == 3

            # Check file was created
            file_path = Path(debug_info["file_path"])
            assert file_path.exists()
            assert file_path.suffix == ".json"

            # Check file content
            with open(file_path, "r") as f:
                data = json.load(f)

            assert "messages" in data
            assert "tools" in data
            assert len(data["messages"]) == 3
            assert len(data["tools"]) == 3

            # Check OpenAI format
            assert data["tools"][0]["type"] == "function"
            assert "function" in data["tools"][0]

    @pytest.mark.asyncio
    async def test_export_anthropic_schema(self):
        """Test Anthropic schema export"""
        # Mock user_select to return Anthropic option (index 2)
        # Mock subprocess.run to prevent actual file opening
        with pytest.MonkeyPatch().context() as m:
            m.setattr(
                "klaudecode.user_command.command_debug.user_select",
                AsyncMock(return_value=2),
            )
            m.setattr("klaudecode.user_command.command_debug.subprocess.run", Mock())

            user_input = UserInput(
                command_name="debug", cleaned_input="/debug", raw_input="/debug"
            )
            command_output = await self.debug_command.handle(
                self.mock_agent_state, user_input
            )

            # Check export data
            debug_info = command_output.user_msg.get_extra_data("debug_exported")
            assert debug_info["provider"] == "anthropic"

            # Check file content
            file_path = Path(debug_info["file_path"])
            with open(file_path, "r") as f:
                data = json.load(f)

            # Check Anthropic format
            assert "input_schema" in data["tools"][0]
            assert "type" not in data["tools"][0]  # No 'type' field in Anthropic format

    @pytest.mark.asyncio
    async def test_export_anthropic_schema_with_system_messages(self):
        """Test Anthropic schema export with system messages properly separated"""
        # Add system messages to the mock messages
        messages_with_system = [
            MockSystemMessage("You are a helpful assistant"),
            MockMessage("user", "Hello"),
            MockMessage("assistant", "Hi there"),
            MockSystemMessage("Follow safety guidelines"),
            MockMessage("tool", "Tool result"),
        ]
        self.mock_agent_state.session.messages.messages = messages_with_system

        # Mock user_select to return Anthropic option (index 2)
        # Mock subprocess.run to prevent actual file opening
        with pytest.MonkeyPatch().context() as m:
            # Mock the convert_to_anthropic method to return proper separation
            def mock_convert_to_anthropic(msgs):
                system_msgs = [
                    msg.to_anthropic()
                    for msg in msgs
                    if msg.role == "system" and bool(msg)
                ]
                other_msgs = [
                    msg.to_anthropic()
                    for msg in msgs
                    if msg.role != "system" and bool(msg)
                ]
                return system_msgs, other_msgs

            m.setattr(
                "klaudecode.user_command.command_debug.AnthropicProxy.convert_to_anthropic",
                mock_convert_to_anthropic,
            )
            m.setattr(
                "klaudecode.user_command.command_debug.user_select",
                AsyncMock(return_value=2),
            )
            m.setattr("klaudecode.user_command.command_debug.subprocess.run", Mock())

            user_input = UserInput(
                command_name="debug", cleaned_input="/debug", raw_input="/debug"
            )
            command_output = await self.debug_command.handle(
                self.mock_agent_state, user_input
            )

            # Check export data
            debug_info = command_output.user_msg.get_extra_data("debug_exported")
            assert debug_info["provider"] == "anthropic"
            assert debug_info["message_count"] == 3  # Non-system messages

            # Check file content
            file_path = Path(debug_info["file_path"])
            with open(file_path, "r") as f:
                data = json.load(f)

            # Check that system messages are separated
            assert "messages" in data
            assert "system" in data
            assert "tools" in data

            # Should have 2 system messages and 3 non-system messages
            assert len(data["system"]) == 2
            assert len(data["messages"]) == 3

            # Check system messages format
            for sys_msg in data["system"]:
                assert "type" in sys_msg
                assert sys_msg["type"] == "text"
                assert "text" in sys_msg

            # Check that messages don't contain system messages
            for msg in data["messages"]:
                assert msg.get("role") != "system"

    @pytest.mark.asyncio
    async def test_generate_curl_openai(self):
        """Test curl generation for OpenAI"""
        # Mock user_select to return curl option (index 0)
        # Mock subprocess.run to prevent any subprocess calls
        with pytest.MonkeyPatch().context() as m:
            m.setattr(
                "klaudecode.user_command.command_debug.user_select",
                AsyncMock(return_value=0),
            )
            m.setattr("klaudecode.user_command.command_debug.subprocess.run", Mock())

            user_input = UserInput(
                command_name="debug", cleaned_input="/debug", raw_input="/debug"
            )
            command_output = await self.debug_command.handle(
                self.mock_agent_state, user_input
            )

            # Check export data
            debug_info = command_output.user_msg.get_extra_data("debug_exported")
            assert debug_info["type"] == "curl"
            assert debug_info["provider"] == "openai"

            # Check file was created
            file_path = Path(debug_info["file_path"])
            assert file_path.exists()
            assert file_path.suffix == ".sh"

            # Check file content
            content = file_path.read_text()
            assert "#!/bin/bash" in content
            assert "curl -X POST" in content
            assert "chat/completions?ak=test-key-123" not in content  # URL with API key format changed
            assert "?ak=test-key-123" in content  # New URL format with API key
            assert (
                "Authorization: Bearer test-key-123" in content
            )  # Header with API key
            assert "EOF" in content  # Heredoc format

            # Check file is executable
            assert file_path.stat().st_mode & 0o111  # Check execute permissions

    @pytest.mark.asyncio
    async def test_generate_curl_anthropic(self):
        """Test curl generation for Anthropic"""
        # Update config to Anthropic
        self.mock_config.base_url = ConfigValue("https://api.anthropic.com/v1/", "test")
        self.mock_config.model_name = ConfigValue("claude-3-sonnet", "test")

        # Mock user_select to return curl option (index 0)
        # Mock subprocess.run to prevent any subprocess calls
        with pytest.MonkeyPatch().context() as m:
            m.setattr(
                "klaudecode.user_command.command_debug.user_select",
                AsyncMock(return_value=0),
            )
            m.setattr("klaudecode.user_command.command_debug.subprocess.run", Mock())

            user_input = UserInput(
                command_name="debug", cleaned_input="/debug", raw_input="/debug"
            )
            command_output = await self.debug_command.handle(
                self.mock_agent_state, user_input
            )

            # Check export data
            debug_info = command_output.user_msg.get_extra_data("debug_exported")
            assert debug_info["provider"] == "anthropic"

            # Check file content
            file_path = Path(debug_info["file_path"])
            content = file_path.read_text()
            assert "/messages" in content  # Anthropic endpoint
            assert "x-api-key:" in content  # Anthropic header
            assert "anthropic-version:" in content  # Anthropic version header

    @pytest.mark.asyncio
    async def test_no_config_error(self):
        """Test error handling when no config is available"""
        self.mock_agent_state.config = None

        # Mock user_select to return curl option (index 0)
        # Mock subprocess.run to prevent any subprocess calls
        with pytest.MonkeyPatch().context() as m:
            m.setattr(
                "klaudecode.user_command.command_debug.user_select",
                AsyncMock(return_value=0),
            )
            m.setattr("klaudecode.user_command.command_debug.subprocess.run", Mock())

            user_input = UserInput(
                command_name="debug", cleaned_input="/debug", raw_input="/debug"
            )
            command_output = await self.debug_command.handle(
                self.mock_agent_state, user_input
            )

            # Check error is set
            error = command_output.user_msg.get_extra_data("debug_error")
            assert error == "No LLM configuration found"

    @pytest.mark.asyncio
    async def test_no_api_key_error(self):
        """Test error handling when no API key is available"""
        self.mock_config.api_key = None

        # Mock user_select to return curl option (index 0)
        # Mock subprocess.run to prevent any subprocess calls
        with pytest.MonkeyPatch().context() as m:
            m.setattr(
                "klaudecode.user_command.command_debug.user_select",
                AsyncMock(return_value=0),
            )
            m.setattr("klaudecode.user_command.command_debug.subprocess.run", Mock())

            user_input = UserInput(
                command_name="debug", cleaned_input="/debug", raw_input="/debug"
            )
            command_output = await self.debug_command.handle(
                self.mock_agent_state, user_input
            )

            # Check error is set
            error = command_output.user_msg.get_extra_data("debug_error")
            assert error == "No API key found in configuration"

    @pytest.mark.asyncio
    async def test_user_cancel(self):
        """Test behavior when user cancels selection"""
        # Mock user_select to return None (user canceled)
        # Mock subprocess.run to prevent any subprocess calls
        with pytest.MonkeyPatch().context() as m:
            m.setattr(
                "klaudecode.user_command.command_debug.user_select",
                AsyncMock(return_value=None),
            )
            m.setattr("klaudecode.user_command.command_debug.subprocess.run", Mock())

            user_input = UserInput(
                command_name="debug", cleaned_input="/debug", raw_input="/debug"
            )
            command_output = await self.debug_command.handle(
                self.mock_agent_state, user_input
            )

            # Check that user message is still removed
            assert command_output.user_msg.removed is True

            # Check no export data or error is set
            assert command_output.user_msg.get_extra_data("debug_exported") is None
            assert command_output.user_msg.get_extra_data("debug_error") is None

    def test_provider_detection(self):
        """Test provider detection logic"""
        # Test OpenAI detection
        assert "openai" in self.mock_config.base_url.value

        # Test Anthropic detection
        anthropic_config = Mock()
        anthropic_config.base_url = ConfigValue("https://api.anthropic.com/v1/", "test")
        anthropic_config.model_name = ConfigValue("claude-3", "test")

        assert "anthropic" in anthropic_config.base_url.value

    def test_render_user_msg_suffix_curl(self):
        """Test rendering for curl export"""
        user_msg = UserMessage(
            content="/debug", user_msg_type="debug", user_raw_input="/debug"
        )
        user_msg.set_extra_data(
            "debug_exported",
            {
                "type": "curl",
                "provider": "openai",
                "file_path": "/test/path.sh",
                "message_count": 5,
                "tool_count": 3,
                "role_counts": {"user": 2, "assistant": 2, "tool": 1},
            },
        )

        # Get rendered output
        rendered = list(self.debug_command.render_user_msg_suffix(user_msg))
        assert len(rendered) == 1

        # The rendered output should be a Table (render_suffix returns Table)
        table = rendered[0]
        assert hasattr(table, "columns")  # Table has columns

    def test_render_user_msg_suffix_schema(self):
        """Test rendering for schema export"""
        user_msg = UserMessage(
            content="/debug", user_msg_type="debug", user_raw_input="/debug"
        )
        user_msg.set_extra_data(
            "debug_exported",
            {
                "type": "schema",
                "provider": "anthropic",
                "file_path": "/test/path.json",
                "message_count": 5,
                "tool_count": 3,
                "role_counts": {"user": 2, "assistant": 2, "tool": 1},
            },
        )

        # Get rendered output
        rendered = list(self.debug_command.render_user_msg_suffix(user_msg))
        assert len(rendered) == 1

        # The rendered output should be a Table
        table = rendered[0]
        assert hasattr(table, "columns")

    def test_render_user_msg_suffix_error(self):
        """Test rendering for error case"""
        user_msg = UserMessage(
            content="/debug", user_msg_type="debug", user_raw_input="/debug"
        )
        user_msg.set_extra_data("debug_error", "Test error message")

        # Get rendered output
        rendered = list(self.debug_command.render_user_msg_suffix(user_msg))
        assert len(rendered) == 1

        # Check it returns a Table (from render_suffix)
        table = rendered[0]
        assert hasattr(table, "columns")

    def test_build_curl_commands(self):
        """Test curl command building"""
        messages = [{"role": "user", "content": "test"}]
        tools = [{"name": "test_tool"}]

        # Test OpenAI curl
        openai_curl = self.debug_command._build_openai_curl(
            "https://api.openai.com/v1/",
            "test-key",
            "gpt-4",
            messages,
            tools,
            self.mock_config,
        )

        assert "curl -X POST" in openai_curl
        assert "chat/completions?ak=test-key" not in openai_curl  # URL format changed
        assert "?ak=test-key" in openai_curl  # New URL format with API key
        assert "Authorization: Bearer test-key" in openai_curl
        assert "EOF" in openai_curl

        # Test Anthropic curl
        anthropic_curl = self.debug_command._build_anthropic_curl(
            "https://api.anthropic.com/v1/",
            "test-key",
            "claude-3",
            messages,
            tools,
            self.mock_config,
        )

        assert "curl -X POST" in anthropic_curl
        assert "/messages" in anthropic_curl
        assert "x-api-key: test-key" in anthropic_curl
        assert "anthropic-version:" in anthropic_curl
        assert "EOF" in anthropic_curl


if __name__ == "__main__":
    pytest.main([__file__])
