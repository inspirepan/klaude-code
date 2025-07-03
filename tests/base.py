import tempfile
from pathlib import Path
from typing import Optional, Any
from unittest.mock import Mock

from klaudecode.tool import Tool, ToolCall, ToolInstance
from klaudecode.utils.file_utils import FileTracker


class MockAgent:
    """Mock agent for testing tools."""
    
    def __init__(self, work_dir: Optional[Path] = None):
        self.session = Mock()
        self.session.work_dir = work_dir or Path.cwd()
        self.session.file_tracker = FileTracker()
        self._interrupt_flag = Mock()
        self._interrupt_flag.is_set.return_value = False
    
    def _should_interrupt(self) -> bool:
        return False


class BaseToolTest:
    """Base class for tool testing with temporary directory support."""
    
    def setup_method(self):
        """Set up test environment before each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.mock_agent = MockAgent(self.temp_path)
        
    def teardown_method(self):
        """Clean up after each test."""
        self.temp_dir.cleanup()
        
    def create_test_file(self, name: str, content: str) -> Path:
        """Create a test file in the temporary directory."""
        file_path = self.temp_path / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding='utf-8')
        return file_path
        
    def create_tool_call(self, tool_class: type[Tool], args: dict) -> ToolCall:
        """Create a ToolCall instance for testing."""
        import json
        return ToolCall(
            id='test_call_123',
            tool_name=tool_class.get_name(),
            tool_args=json.dumps(args)
        )
        
    def create_tool_instance(self, tool_class: type[Tool], tool_call: ToolCall) -> ToolInstance:
        """Create a ToolInstance for testing."""
        return tool_class.create_instance(tool_call, self.mock_agent)
        
    def invoke_tool(self, tool_class: type[Tool], args: dict) -> Any:
        """Helper method to invoke a tool synchronously."""
        tool_call = self.create_tool_call(tool_class, args)
        instance = self.create_tool_instance(tool_class, tool_call)
        
        # Run the tool
        tool_class.invoke(tool_call, instance)
        
        # Check if status was updated, if still processing, set to success
        result = instance.tool_result()
        if result.tool_call.status == 'processing' and not result.error_msg:
            result.tool_call.status = 'success'
        
        # Return the result
        return result
    
    async def invoke_tool_async(self, tool_class: type[Tool], args: dict) -> Any:
        """Helper method to invoke a tool asynchronously."""
        tool_call = self.create_tool_call(tool_class, args)
        instance = self.create_tool_instance(tool_class, tool_call)
        
        # Run the tool
        await tool_class.invoke_async(tool_call, instance)
        
        # Return the result
        return instance.tool_result()