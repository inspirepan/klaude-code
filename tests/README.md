# Testing Guide for klaude-code

## Installation

First, install the test dependencies:

```bash
# Using uv (recommended)
uv sync --group test

# Or using pip
pip install -e ".[test]"
```

## Running Tests

### Run all tests
```bash
pytest

# Or use the test runner script
python tests/run_tests.py
```

### Run specific test files
```bash
pytest tests/tools/test_read.py
pytest tests/tools/test_write.py
pytest tests/tools/test_edit.py
```

### Run with verbose output
```bash
pytest -v
```

### Run with coverage report
```bash
pytest --cov=klaudecode --cov-report=html
# Or
python tests/run_tests.py --cov
```

### Run specific test methods
```bash
pytest tests/tools/test_read.py::TestReadTool::test_read_existing_file
```

## Test Structure

```
tests/
├── __init__.py
├── base.py              # Base test classes and utilities
├── conftest.py          # Pytest configuration and fixtures
├── run_tests.py         # Test runner script
├── tools/               # Tool-specific tests
│   ├── __init__.py
│   ├── test_read.py     # Tests for Read tool
│   ├── test_write.py    # Tests for Write tool
│   └── test_edit.py     # Tests for Edit tool
└── utils/               # Utility tests (future)
    └── __init__.py
```

## Writing New Tests

1. **For Tools**: Extend `BaseToolTest` class
2. **Use Temporary Directories**: Tests automatically use temp directories
3. **Mock Agent**: Use `self.mock_agent` for agent-dependent functionality
4. **File Operations**: Use `self.create_test_file()` helper method

### Example Test

```python
from tests.base import BaseToolTest
from klaudecode.tools.your_tool import YourTool

class TestYourTool(BaseToolTest):
    def test_basic_functionality(self):
        # Create test files if needed
        test_file = self.create_test_file("test.txt", "content")
        
        # Invoke the tool
        result = self.invoke_tool(YourTool, {
            'param1': 'value1',
            'param2': 'value2'
        })
        
        # Assert results
        assert result.tool_call.status == 'success'
        assert "expected output" in result.content
```

## Testing Best Practices

1. **Isolation**: Each test should be independent
2. **Cleanup**: Temp directories are automatically cleaned up
3. **Edge Cases**: Test error conditions and edge cases
4. **File System**: Always use absolute paths in tests
5. **Mocking**: Mock external dependencies when needed

## Continuous Integration

Add this to your CI pipeline:

```yaml
- name: Run tests
  run: |
    uv sync --group test
    pytest --cov=klaudecode --cov-report=xml
```