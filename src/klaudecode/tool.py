import json
from abc import ABC, abstractmethod
from typing import Any, Dict

from .message import ToolCallMessage, ToolMessage


def tool_input(pydantic_model):
    """
    Decorator: Automatically generate Tool's parameters field from Pydantic model

    Usage:
    @tool_input
    class Input(BaseModel):
        command: str = Field(description="The command to execute")
    """
    schema = pydantic_model.model_json_schema()

    # Convert schema to OpenAI tool parameters format
    parameters = {
        "type": "object",
        "properties": schema.get("properties", {}),
        "required": schema.get("required", [])
    }

    import inspect
    frame = inspect.currentframe()
    try:
        # Look up to find the frame containing class definition
        caller_frame = frame.f_back
        caller_locals = caller_frame.f_locals

        if '__qualname__' in caller_locals and '__module__' in caller_locals:
            caller_locals['parameters'] = parameters
            caller_locals['InputModel'] = pydantic_model
    finally:
        del frame

    return pydantic_model


class Tool(ABC):

    name: str = ""
    desc: str = ""
    parameters: Dict[str, Any] = {}

    @classmethod
    def get_name(cls) -> str:
        return cls.name

    @classmethod
    def get_desc(cls) -> str:
        return cls.desc

    @classmethod
    def get_parameters(cls) -> Dict[str, Any]:
        return cls.parameters

    @classmethod
    def openai_schema(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": cls.get_name(),
                "description": cls.get_desc(),
                "parameters": cls.get_parameters(),
            },
        }

    def __str__(self) -> str:
        return self.json_openai_schema()

    def __repr__(self) -> str:
        return self.json_openai_schema()

    @classmethod
    def json_openai_schema(cls):
        return json.dumps(cls.openai_schema())

    @abstractmethod
    def invoke(tool_call: ToolCallMessage) -> ToolMessage:
        raise NotImplementedError
