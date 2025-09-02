from typing import Literal

from pydantic import BaseModel


class Config(BaseModel):
    protocal: Literal["chat_completion", "responses", "anthropic"] = "responses"
    pass
