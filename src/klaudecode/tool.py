from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
import json
from .message import ToolCallMessage, ToolMessage
from rich.live import Live


class Tool(ABC):
    @abstractmethod
    def schema() -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def name() -> str:
        raise NotImplementedError

    @abstractmethod
    def desc() -> str:
        raise NotImplementedError

    @abstractmethod
    def parameters() -> Dict[str, Any]:
        raise NotImplementedError

    def __str__(self) -> str:
        return self.json_schema()

    def __repr__(self) -> str:
        return self.json_schema()

    def json_schema(self):
        return json.dumps(self.schema())

    @abstractmethod
    def invoke(tool_call: ToolCallMessage, live: Optional[Live]) -> ToolMessage:
        raise NotImplementedError



