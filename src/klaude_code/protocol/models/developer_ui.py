from typing import Literal

from pydantic import BaseModel, Field


class MemoryFileLoaded(BaseModel):
    path: str


class MemoryLoadedUIItem(BaseModel):
    type: Literal["memory_loaded"] = "memory_loaded"
    files: list[MemoryFileLoaded]


class ExternalFileChangesUIItem(BaseModel):
    type: Literal["external_file_changes"] = "external_file_changes"
    paths: list[str]


class TodoAttachmentUIItem(BaseModel):
    type: Literal["todo_attachment"] = "todo_attachment"
    reason: Literal["empty", "not_used_recently"]


class AtFileOp(BaseModel):
    operation: Literal["Read", "List"]
    path: str


class AtFileOpsUIItem(BaseModel):
    type: Literal["at_file_ops"] = "at_file_ops"
    ops: list[AtFileOp]


class UserImagesUIItem(BaseModel):
    type: Literal["user_images"] = "user_images"
    count: int
    paths: list[str] = Field(default_factory=list)


class SkillActivatedUIItem(BaseModel):
    type: Literal["skill_activated"] = "skill_activated"
    name: str


class SkillDiscoveredUIItem(BaseModel):
    type: Literal["skill_discovered"] = "skill_discovered"
    name: str


class SkillListingUIItem(BaseModel):
    type: Literal["skill_listing"] = "skill_listing"
    names: list[str]
    incremental: bool = False


class AtFileImagesUIItem(BaseModel):
    type: Literal["at_file_images"] = "at_file_images"
    paths: list[str]


class PasteFilesUIItem(BaseModel):
    type: Literal["paste_files"] = "paste_files"
    tags: dict[str, str]


DeveloperUIItem = (
    MemoryLoadedUIItem
    | ExternalFileChangesUIItem
    | TodoAttachmentUIItem
    | AtFileOpsUIItem
    | UserImagesUIItem
    | SkillActivatedUIItem
    | SkillDiscoveredUIItem
    | SkillListingUIItem
    | AtFileImagesUIItem
    | PasteFilesUIItem
)


def _empty_developer_ui_items() -> list[DeveloperUIItem]:
    return []


class DeveloperUIExtra(BaseModel):
    items: list[DeveloperUIItem] = Field(default_factory=_empty_developer_ui_items)


__all__ = [
    "AtFileImagesUIItem",
    "AtFileOp",
    "AtFileOpsUIItem",
    "DeveloperUIExtra",
    "DeveloperUIItem",
    "ExternalFileChangesUIItem",
    "MemoryFileLoaded",
    "MemoryLoadedUIItem",
    "PasteFilesUIItem",
    "SkillActivatedUIItem",
    "SkillDiscoveredUIItem",
    "SkillListingUIItem",
    "TodoAttachmentUIItem",
    "UserImagesUIItem",
]
