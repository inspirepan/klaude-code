import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Callable
from pydantic import BaseModel
from .message import ToolCallMessage, ToolMessage
import threading


class Tool(ABC):
    name: str = ""
    desc: str = ""
    parallelable: bool = True
    timeout = 60

    @classmethod
    def get_name(cls) -> str:
        return cls.name

    @classmethod
    def get_desc(cls) -> str:
        return cls.desc

    @classmethod
    def is_parallelable(cls) -> bool:
        return cls.parallelable

    @classmethod
    def get_timeout(cls) -> float:
        return cls.timeout

    @classmethod
    def get_parameters(cls) -> Dict[str, Any]:
        if hasattr(cls, 'parameters'):
            return cls.parameters

        if hasattr(cls, 'Input') and issubclass(cls.Input, BaseModel):
            schema = cls.Input.model_json_schema()
            return {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", [])
            }

        return {"type": "object", "properties": {}, "required": []}

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

    @classmethod
    def create_instance(cls, tool_call: ToolCallMessage) -> 'ToolInstance':
        return ToolInstance(tool=cls, tool_call=tool_call)

    @classmethod
    def parse_input_args(cls, tool_call: ToolCallMessage) -> Optional[BaseModel]:
        if hasattr(cls, 'Input') and issubclass(cls.Input, BaseModel):
            args_dict = json.loads(tool_call.tool_args)
            return cls.Input(**args_dict)
        return None

    @abstractmethod
    def invoke(self, tool_call: ToolCallMessage, instance: 'ToolInstance') -> ToolMessage:
        raise NotImplementedError


class ToolInstance:
    def __init__(self, tool: type[Tool], tool_call: ToolCallMessage):
        self.tool = tool
        self.tool_call = tool_call
        self.tool_msg = ToolMessage(tool_call=tool_call)
        self.input = self.get_input()
        self.thread = None

    def get_input(self) -> Optional[BaseModel]:
        if hasattr(self.tool, 'Input'):
            args_dict = json.loads(self.tool_call.tool_args)
            return self.tool.Input(**args_dict)
        return None

    def get_tool_message(self) -> ToolMessage:
        return self.tool_msg

    def start_thread(self) -> threading.Thread:
        # TODO 完善 Timeout，包括 Timeout 后更新 tool_msg
        if not self.thread:
            self.thread = threading.Thread(target=self.tool.invoke, args=(self.tool_call, self), daemon=True)
            self.thread.start()
        return self.thread

    def is_running(self):
        return self.thread and self.thread.is_alive()

    def join(self):
        if self.thread:
            self.thread.join()

    def stop_thread(self):
        # TODO
        pass
