import pytest

from klaude_code.llm.openai_compatible.tool_call_accumulator import normalize_tool_name


class TestNormalizeToolName:
    @pytest.mark.parametrize(
        ("input_name", "expected"),
        [
            ("tool_Edit_mUoY2p3W3r3z8uO5P2nZ", "Edit"),
            ("tool_Bash_abc123XYZ", "Bash"),
            ("tool_Read_A1b2C3d4E5", "Read"),
            ("tool_Write_ABCDEFGHIJ", "Write"),
            ("Edit", "Edit"),
            ("Bash", "Bash"),
            ("tool_Edit", "tool_Edit"),
            ("tool__abc123", "tool__abc123"),
            ("tool_123_abc", "tool_123_abc"),
            ("", ""),
        ],
    )
    def test_normalize_tool_name(self, input_name: str, expected: str) -> None:
        assert normalize_tool_name(input_name) == expected
