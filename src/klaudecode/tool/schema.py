import json
from typing import Any, Dict

from pydantic import BaseModel

from ..message import count_tokens


class ToolSchema:
    """Handles tool schema generation and parameter parsing."""

    @staticmethod
    def get_parameters(tool_class: type) -> Dict[str, Any]:
        """Get tool parameters schema."""
        if hasattr(tool_class, 'parameters'):
            return tool_class.parameters

        if ToolSchema._has_input_model(tool_class):
            return ToolSchema._get_parameters_from_input_model(tool_class)

        return ToolSchema._get_default_parameters()

    @staticmethod
    def _has_input_model(tool_class: type) -> bool:
        """Check if the tool has an Input model."""
        return hasattr(tool_class, 'Input') and issubclass(tool_class.Input, BaseModel)

    @staticmethod
    def _get_parameters_from_input_model(tool_class: type) -> Dict[str, Any]:
        """Extract parameters from the Input model."""
        schema = tool_class.Input.model_json_schema()
        return ToolSchema._resolve_schema_refs(schema)

    @staticmethod
    def _get_default_parameters() -> Dict[str, Any]:
        """Return default empty parameters schema."""
        return {'type': 'object', 'properties': {}, 'required': []}

    @staticmethod
    def _resolve_schema_refs(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve JSON schema references ($ref) in the schema."""
        defs = schema.get('$defs', {})

        result = {
            'type': 'object',
            'properties': ToolSchema._resolve_refs_in_object(schema.get('properties', {}), defs),
            'required': schema.get('required', []),
            'additionalProperties': False,
        }

        return result

    @staticmethod
    def _resolve_refs_in_object(obj: Any, defs_map: Dict[str, Any]) -> Any:
        """Recursively resolve references in an object."""
        if isinstance(obj, dict):
            if '$ref' in obj:
                return ToolSchema._resolve_single_ref(obj, defs_map)
            else:
                result = {}
                for k, v in obj.items():
                    if k != 'title':  # Remove unneeded title fields
                        result[k] = ToolSchema._resolve_refs_in_object(v, defs_map)
                return result
        elif isinstance(obj, list):
            return [ToolSchema._resolve_refs_in_object(item, defs_map) for item in obj]
        else:
            return obj

    @staticmethod
    def _resolve_single_ref(ref_obj: Dict[str, Any], defs_map: Dict[str, Any]) -> Any:
        """Resolve a single $ref object."""
        ref_path = ref_obj['$ref']
        if ref_path.startswith('#/$defs/'):
            def_name = ref_path.split('/')[-1]
            if def_name in defs_map:
                resolved = defs_map[def_name].copy()
                return ToolSchema._resolve_refs_in_object(resolved, defs_map)
        return ref_obj

    @staticmethod
    def openai_schema(tool_class: type) -> Dict[str, Any]:
        """Generate OpenAI compatible schema."""
        return {
            'type': 'function',
            'function': {
                'name': tool_class.get_name(),
                'description': tool_class.get_desc(),
                'parameters': ToolSchema.get_parameters(tool_class),
            },
        }

    @staticmethod
    def anthropic_schema(tool_class: type) -> Dict[str, Any]:
        """Generate Anthropic compatible schema."""
        return {
            'name': tool_class.get_name(),
            'description': tool_class.get_desc(),
            'input_schema': ToolSchema.get_parameters(tool_class),
        }

    @staticmethod
    def calculate_tokens(tool_class: type) -> int:
        """Calculate total tokens for tool description and parameters."""
        cache_attr = '_cached_tokens'
        if hasattr(tool_class, cache_attr):
            return getattr(tool_class, cache_attr)

        desc_tokens = count_tokens(tool_class.get_desc())
        params = ToolSchema.get_parameters(tool_class)
        params_text = json.dumps(params, ensure_ascii=False)
        params_tokens = count_tokens(params_text)

        total_tokens = desc_tokens + params_tokens
        setattr(tool_class, cache_attr, total_tokens)
        return total_tokens
