from typing import Literal

from pydantic import BaseModel, Field

ContextCategoryKey = Literal[
    "system_prompt",
    "system_tools",
    "memory",
    "skills",
    "messages",
    "autocompact_reserve",
    "free",
]


class ContextCategory(BaseModel):
    """One slice of the context window."""

    key: ContextCategoryKey
    label: str
    tokens: int


class ContextDetailEntry(BaseModel):
    """A single item inside a category's breakdown (one memory file, one skill, ...)."""

    name: str
    tokens: int


class ContextDetailSection(BaseModel):
    """Per-category itemization shown under the summary."""

    key: ContextCategoryKey
    label: str
    hint: str = ""
    entries: list[ContextDetailEntry] = Field(default_factory=lambda: [])


class ContextUsageUIExtra(BaseModel):
    """Estimated context-window usage, split by category.

    ``tokens`` values are local estimates. When the session already has a real API usage
    report, the estimates are scaled so their total matches it -- ``is_calibrated`` says
    whether that happened, so the UI can label the numbers honestly.
    """

    model_name: str
    model_id: str
    used_tokens: int
    context_limit: int
    categories: list[ContextCategory] = Field(default_factory=lambda: [])
    details: list[ContextDetailSection] = Field(default_factory=lambda: [])
    is_calibrated: bool = False

    @property
    def usage_percent(self) -> float:
        if self.context_limit <= 0:
            return 0.0
        return self.used_tokens / self.context_limit * 100
