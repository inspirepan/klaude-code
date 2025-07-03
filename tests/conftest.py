import pytest
import tempfile
import sys
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def mock_agent(temp_dir):
    """Create a mock agent for testing."""
    from tests.base import MockAgent
    return MockAgent(temp_dir)