import json
import os
import time
import uuid
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .message import BasicMessage


class Session(BaseModel):
    messages: List[BasicMessage] = Field(default_factory=list)
    # todo_list: List[Todo] = Field(default_factory=list)
    work_dir: str
    title: str = ""
    session_id: str = ""

    def __init__(
        self, work_dir: str, messages: Optional[List[BasicMessage]] = None
    ) -> "Session":
        # Initialize with proper Pydantic model initialization
        super().__init__(
            work_dir=work_dir,
            messages=messages or [],
            session_id=str(uuid.uuid4()),
            title="",
        )

    def append_message(self, msg: BasicMessage):
        self.messages.append(msg)
