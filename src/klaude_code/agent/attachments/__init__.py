from __future__ import annotations

from klaude_code.protocol import message
from klaude_code.session import Session

from . import collection as _collection
from . import files as _files
from . import memory as _memory
from . import skills as _skills
from . import state as _state
from . import todo as _todo

Attachment = _collection.Attachment
collect_attachments = _collection.collect_attachments

AT_FILE_PATTERN = _files.AT_FILE_PATTERN
AtFileRef = _files.AtFileRef
get_at_patterns = _files.get_at_patterns
get_last_user_message_image_paths = _files.get_last_user_message_image_paths
image_attachment = _files.image_attachment
paste_file_attachment = _files.paste_file_attachment
file_changed_externally_attachment = _files.file_changed_externally_attachment

AUTO_MEMORY_MAX_LINES = _memory.AUTO_MEMORY_MAX_LINES
MEMORY_MAX_SESSION_BYTES = _memory.MEMORY_MAX_SESSION_BYTES
Memory = _memory.Memory
discover_memory_files_near_paths = _memory.discover_memory_files_near_paths
format_memories_attachment = _memory.format_memories_attachment
format_memory_content = _memory.format_memory_content
get_auto_memory_path = _memory.get_auto_memory_path
get_existing_memory_files = _memory.get_existing_memory_files
get_existing_memory_paths_by_location = _memory.get_existing_memory_paths_by_location
get_memory_paths = _memory.get_memory_paths
last_path_memory_attachment = _memory.last_path_memory_attachment
load_auto_memory = _memory.load_auto_memory
memory_attachment = _memory.memory_attachment
truncate_memory_content = _memory.truncate_memory_content

SYSTEM_SKILL_LISTING_MARKER_NAME = _skills.SYSTEM_SKILL_LISTING_MARKER_NAME
SkillLoader = _skills.SkillLoader
build_dynamic_skill_listing_attachment = _skills.build_dynamic_skill_listing_attachment
get_skills_from_user_input = _skills.get_skills_from_user_input
last_path_skill_attachment = _skills.last_path_skill_attachment

# Compatibility exports for existing monkeypatch-based tests.
_format_available_skills_str = _skills.format_available_skills_str
_get_available_skills_for_session = _skills.get_available_skills_for_session
_get_static_skill_loader_for_session = _skills.get_static_skill_loader_for_session

TODO_ATTACHMENT_TURNS_BETWEEN = _todo.TODO_ATTACHMENT_TURNS_BETWEEN
TODO_ATTACHMENT_TURNS_SINCE_WRITE = _todo.TODO_ATTACHMENT_TURNS_SINCE_WRITE
todo_attachment = _todo.todo_attachment

_is_memory_loaded = _state.is_memory_loaded
_is_tracked_file_unchanged = _state.is_tracked_file_unchanged
_mark_directory_accessed = _state.mark_directory_accessed
_mark_memory_loaded = _state.mark_memory_loaded


async def at_file_reader_attachment(session: Session) -> message.DeveloperMessage | None:
    return await _files.at_file_reader_attachment(
        session,
        build_dynamic_skill_listing_attachment=build_dynamic_skill_listing_attachment,
    )


def _resolve_skill_for_input(session: Session, skill_name: str):
    dynamic_exact = _skills.find_dynamic_skill(session, skill_name)
    if dynamic_exact is not None:
        return dynamic_exact

    static_loader = _get_static_skill_loader_for_session(session)
    static_exact = static_loader.loaded_skills.get(skill_name)
    if static_exact is not None:
        return static_exact

    if ":" in skill_name:
        dynamic_short = _skills.find_dynamic_skill(session, skill_name, allow_short_fallback=True)
        if dynamic_short is not None:
            return dynamic_short
        return static_loader.get_skill(skill_name.split(":")[-1])

    return static_loader.get_skill(skill_name)


async def available_skills_attachment(session: Session) -> message.DeveloperMessage | None:
    return await _skills.available_skills_attachment_for(
        session,
        get_available_skills_for_session_fn=_get_available_skills_for_session,
    )


async def skill_attachment(session: Session) -> message.DeveloperMessage | None:
    return await _skills.skill_attachment_for(
        session,
        resolve_skill_for_input_fn=_resolve_skill_for_input,
    )


__all__ = [
    "AT_FILE_PATTERN",
    "AUTO_MEMORY_MAX_LINES",
    "MEMORY_MAX_SESSION_BYTES",
    "SYSTEM_SKILL_LISTING_MARKER_NAME",
    "TODO_ATTACHMENT_TURNS_BETWEEN",
    "TODO_ATTACHMENT_TURNS_SINCE_WRITE",
    "AtFileRef",
    "Attachment",
    "Memory",
    "SkillLoader",
    "at_file_reader_attachment",
    "available_skills_attachment",
    "build_dynamic_skill_listing_attachment",
    "collect_attachments",
    "discover_memory_files_near_paths",
    "file_changed_externally_attachment",
    "format_memories_attachment",
    "format_memory_content",
    "get_at_patterns",
    "get_auto_memory_path",
    "get_existing_memory_files",
    "get_existing_memory_paths_by_location",
    "get_last_user_message_image_paths",
    "get_memory_paths",
    "get_skills_from_user_input",
    "image_attachment",
    "last_path_memory_attachment",
    "last_path_skill_attachment",
    "load_auto_memory",
    "memory_attachment",
    "paste_file_attachment",
    "skill_attachment",
    "todo_attachment",
    "truncate_memory_content",
]