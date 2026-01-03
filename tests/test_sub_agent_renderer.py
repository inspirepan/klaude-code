"""Tests for sub-agent renderer compact schema functions."""

# pyright: reportPrivateUsage=false
from __future__ import annotations

from klaude_code.tui.components.sub_agent import _compact_schema, _compact_schema_value


class TestCompactSchemaValue:
    """Tests for _compact_schema_value function."""

    def test_simple_string_with_description(self) -> None:
        """String type with description should include the description."""
        schema = {"type": "string", "description": "A user name"}
        result = _compact_schema_value(schema)
        assert result == "string // A user name"

    def test_simple_string_without_description(self) -> None:
        """String type without description should return just the type."""
        schema = {"type": "string"}
        result = _compact_schema_value(schema)
        assert result == "string"

    def test_simple_integer_with_description(self) -> None:
        """Integer type with description should include the description."""
        schema = {"type": "integer", "description": "User age in years"}
        result = _compact_schema_value(schema)
        assert result == "integer // User age in years"

    def test_object_with_properties(self) -> None:
        """Object type should recursively compact its properties."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "User name"},
                "age": {"type": "integer"},
            },
        }
        result = _compact_schema_value(schema)
        assert result == {
            "name": "string // User name",
            "age": "integer",
        }

    def test_array_with_string_items(self) -> None:
        """Array of strings should return list with compacted item type."""
        schema = {
            "type": "array",
            "items": {"type": "string"},
        }
        result = _compact_schema_value(schema)
        assert result == ["string"]

    def test_array_with_string_items_and_item_description(self) -> None:
        """Array with item description should include item description."""
        schema = {
            "type": "array",
            "items": {"type": "string", "description": "A tag name"},
        }
        result = _compact_schema_value(schema)
        assert result == ["string // A tag name"]

    def test_array_with_own_description_should_preserve_it(self) -> None:
        """Array type with its own description should preserve it.

        This is the bug case: when array has a description like
        'key_techniques' with description '关键技术点列表',
        the description should be preserved somehow.
        """
        schema = {
            "type": "array",
            "items": {"type": "string"},
            "description": "关键技术点列表",
        }
        result = _compact_schema_value(schema)
        # Current buggy behavior returns just ["string"]
        # After fix, it should include the array's description
        # For now, we document the expected behavior
        assert result == ["string // 关键技术点列表"]

    def test_array_with_both_array_and_item_descriptions(self) -> None:
        """Array with both array and item descriptions - item description takes precedence."""
        schema = {
            "type": "array",
            "items": {"type": "string", "description": "A single key technique"},
            "description": "关键技术点列表",
        }
        result = _compact_schema_value(schema)
        # When items have their own description, use that
        assert result == ["string // A single key technique"]

    def test_nested_object_in_array(self) -> None:
        """Array of objects should recursively compact the object schema."""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "Item ID"},
                    "name": {"type": "string"},
                },
            },
        }
        result = _compact_schema_value(schema)
        assert result == [{"id": "integer // Item ID", "name": "string"}]

    def test_missing_type_defaults_to_any(self) -> None:
        """Schema without type should default to 'any'."""
        schema = {"description": "Unknown type"}
        result = _compact_schema_value(schema)
        assert result == "any // Unknown type"


class TestCompactSchema:
    """Tests for _compact_schema function."""

    def test_full_schema_example(self) -> None:
        """Test the full schema from the user's example."""
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "文章标题"},
                "main_content": {"type": "string", "description": "文章主要内容，包括所有技术细节"},
                "training_approach": {"type": "string", "description": "训练方法的详细描述"},
                "data_construction": {"type": "string", "description": "训练数据构建方法"},
                "model_architecture": {"type": "string", "description": "模型架构描述"},
                "key_techniques": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "关键技术点列表",
                },
            },
            "required": ["title", "main_content"],
        }
        result = _compact_schema(schema)
        assert isinstance(result, dict)
        # key_techniques should include the description
        assert result["key_techniques"] == ["string // 关键技术点列表"]
        # Other fields should work correctly
        assert result["title"] == "string // 文章标题"
        assert result["main_content"] == "string // 文章主要内容，包括所有技术细节"

    def test_simple_string_schema(self) -> None:
        """Test schema that is just a simple type."""
        schema = {"type": "string", "description": "A simple value"}
        result = _compact_schema(schema)
        assert result == "string // A simple value"
