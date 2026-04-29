from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, cast

from klaude_code.const import ATTACHMENT_SKILL_MAX_LINES
from klaude_code.prompts.attachments import (
    AVAILABLE_SKILLS_ADDED_TEMPLATE,
    AVAILABLE_SKILLS_TEMPLATE,
    DYNAMIC_AVAILABLE_SKILLS_TEMPLATE,
    SKILL_ALREADY_IN_CONTEXT_TEMPLATE,
    SKILL_BLOCK_TEMPLATE,
    SKILL_CONTENT_TRUNCATED_TEMPLATE,
    SKILL_DISCOVERED_PREFACE_TEMPLATE,
    SKILL_EXPLICIT_PREFACE_TEMPLATE,
)
from klaude_code.protocol import message, tools
from klaude_code.protocol.models import (
    DeveloperUIExtra,
    DeveloperUIItem,
    FileStatus,
    SkillActivatedUIItem,
    SkillDiscoveredUIItem,
    SkillListingUIItem,
)
from klaude_code.session import Session
from klaude_code.skill.loader import (
    Skill,
    SkillLoader,
    discover_skills_near_paths,
    extract_skill_listing_paths_from_xml,
)
from klaude_code.skill.system_skills import install_system_skills
from klaude_code.tool.file._utils import hash_text_sha256

from . import truncate_text_by_lines
from .state import is_tracked_file_unchanged

# Match /skill:xxx or //skill:xxx inline (at start of line or after whitespace).
SLASH_SKILL_PATTERN = re.compile(r"(?:^|\s)(?://|/)skill:(?P<skill>[^\s/]+)(?=\s|$)")
SYSTEM_SKILL_LISTING_MARKER_NAME = ".klaude-system-skill-listing"


def _fmt_skill_block(
    skill_name: str,
    skill_path: Path,
    base_dir: Path,
    skill_content: str,
    *,
    explicit: bool,
) -> str:
    if explicit:
        preface = SKILL_EXPLICIT_PREFACE_TEMPLATE.format(skill_name=skill_name)
    else:
        preface = SKILL_DISCOVERED_PREFACE_TEMPLATE.format(skill_name=skill_name)
    return SKILL_BLOCK_TEMPLATE.format(
        preface=preface,
        skill_name=skill_name,
        skill_path=skill_path,
        base_dir=base_dir,
        skill_content=skill_content,
    )


def _fmt_dynamic_available_skills(skills_xml: str) -> str:
    return DYNAMIC_AVAILABLE_SKILLS_TEMPLATE.format(skills_xml=skills_xml)


def _fmt_available_skills(skills_xml: str) -> str:
    return AVAILABLE_SKILLS_TEMPLATE.format(skills_xml=skills_xml)


def _fmt_available_skills_added(skills_xml: str) -> str:
    return AVAILABLE_SKILLS_ADDED_TEMPLATE.format(skills_xml=skills_xml)


def _fmt_skill_already_in_context(skill_name: str, path: str, read_tool_name: str) -> str:
    return SKILL_ALREADY_IN_CONTEXT_TEMPLATE.format(
        skill_name=skill_name,
        path=path,
        read_tool_name=read_tool_name,
    )


def get_skills_from_user_input(session: Session) -> list[str]:
    for item in reversed(session.conversation_history):
        if isinstance(item, message.ToolResultMessage):
            return []
        if isinstance(item, message.UserMessage):
            content = message.join_text_parts(item.parts)
            seen: set[str] = set()
            result: list[str] = []
            for match in SLASH_SKILL_PATTERN.finditer(content):
                name = match.group("skill")
                if name not in seen:
                    seen.add(name)
                    result.append(name)
            return result
    return []


def _get_dynamic_skills_for_session(session: Session) -> list[Skill]:
    if not session.file_tracker:
        return []
    return discover_skills_near_paths(session.file_tracker.keys(), work_dir=session.work_dir)


def find_dynamic_skill(session: Session, name: str, *, allow_short_fallback: bool = False) -> Skill | None:
    dynamic_skills = _get_dynamic_skills_for_session(session)
    by_name = {skill.name: skill for skill in dynamic_skills}

    skill = by_name.get(name)
    if skill is not None:
        return skill
    if allow_short_fallback and ":" in name:
        return by_name.get(name.split(":")[-1])
    return None


def get_static_skill_loader_for_session(session: Session) -> SkillLoader:
    install_system_skills()
    loader = SkillLoader()
    loader.discover_skills(work_dir=session.work_dir)
    return loader


def resolve_skill_for_input(session: Session, skill_name: str) -> Skill | None:
    dynamic_exact = find_dynamic_skill(session, skill_name)
    if dynamic_exact is not None:
        return dynamic_exact

    static_loader = get_static_skill_loader_for_session(session)
    static_exact = static_loader.loaded_skills.get(skill_name)
    if static_exact is not None:
        return static_exact

    if ":" in skill_name:
        dynamic_short = find_dynamic_skill(session, skill_name, allow_short_fallback=True)
        if dynamic_short is not None:
            return dynamic_short
        return static_loader.get_skill(skill_name.split(":")[-1])

    return static_loader.get_skill(skill_name)


def _read_skill_content(skill: Skill) -> str | None:
    if not skill.skill_path.exists() or not skill.skill_path.is_file():
        return None
    content = skill.skill_path.read_text(encoding="utf-8", errors="replace")
    return content or None


def _render_skill_inline_content(raw_content: str, skill: Skill) -> str:
    """Cap inlined SKILL.md for the <system-reminder> block.

    Mirrors Read tool behaviour: keep the first ``ATTACHMENT_SKILL_MAX_LINES``
    lines and tell the agent how to fetch the rest. Returning the raw content
    unchanged when it fits preserves the existing behaviour for small skills.

    The raw content (not the rendered/truncated version) should still be used
    when computing the skill's file-tracker sha256; otherwise a truncated skill
    would be re-classified as "changed" on every turn.
    """
    truncation = truncate_text_by_lines(raw_content, max_lines=ATTACHMENT_SKILL_MAX_LINES)
    if not truncation.truncated:
        return truncation.text
    return truncation.text + SKILL_CONTENT_TRUNCATED_TEMPLATE.format(
        max_lines=ATTACHMENT_SKILL_MAX_LINES,
        total_lines=truncation.total_lines,
        path=str(skill.skill_path),
    )


def _mark_skill_loaded(session: Session, path: str, content: str, *, source: Literal["dynamic", "explicit"]) -> None:
    existing = session.file_tracker.get(path)
    try:
        mtime = Path(path).stat().st_mtime
    except (OSError, FileNotFoundError):
        mtime = 0.0
    session.file_tracker[path] = FileStatus(
        mtime=mtime,
        content_sha256=hash_text_sha256(content),
        cached_content=existing.cached_content if existing else None,
        is_memory=existing.is_memory if existing else False,
        is_skill=True,
        is_skill_listing=existing.is_skill_listing if existing else False,
        skill_attachment_source=source,
        is_directory=existing.is_directory if existing else False,
        read_complete=existing.read_complete if existing else False,
    )


def _get_loaded_skill_paths_by_name(session: Session, *, dynamic_only: bool) -> dict[str, str]:
    loader = SkillLoader()
    result: dict[str, str] = {}
    for path, status in session.file_tracker.items():
        if not status.is_skill:
            continue
        if dynamic_only and status.skill_attachment_source != "dynamic":
            continue
        skill = loader.load_skill(Path(path), location="project")
        if skill is None:
            continue
        result[skill.name] = path
    return result


def _format_skill_block_str(skill: Skill, skill_content: str, *, explicit: bool) -> str:
    return _fmt_skill_block(
        skill_name=skill.name,
        skill_path=skill.skill_path,
        base_dir=skill.base_dir,
        skill_content=_render_skill_inline_content(skill_content, skill),
        explicit=explicit,
    )


def _is_skill_content_already_in_context(session: Session, path: str) -> bool:
    status = session.file_tracker.get(path)
    if status is None:
        return False
    if not status.read_complete and status.skill_attachment_source != "explicit":
        return False
    return is_tracked_file_unchanged(session, path)


def _build_skills_xml(skills: Sequence[Skill]) -> str:
    loader = SkillLoader()
    loader.loaded_skills = {skill.name: skill for skill in _sort_skills_for_listing(skills)}
    return loader.get_skills_xml().rstrip()


def _format_dynamic_available_skills_str(skills: list[Skill]) -> str:
    return _fmt_dynamic_available_skills(_build_skills_xml(skills))


def format_available_skills_str(skills: list[Skill]) -> str:
    return _fmt_available_skills(_build_skills_xml(skills))


def _sort_skills_for_listing(skills: Sequence[Skill]) -> list[Skill]:
    location_order = {"project": 0, "user": 1, "system": 2}
    return sorted(skills, key=lambda skill: (location_order.get(skill.location, 3), skill.name))


def _get_system_skill_listing_marker_path(session: Session) -> str:
    return str((session.work_dir / SYSTEM_SKILL_LISTING_MARKER_NAME).resolve())


def _extract_skill_listing_paths(message_item: message.DeveloperMessage) -> tuple[dict[str, str], bool] | None:
    if message_item.ui_extra is None:
        return None

    listing_items = [item for item in message_item.ui_extra.items if isinstance(item, SkillListingUIItem)]
    if not listing_items:
        return None

    listed_names = {name for item in listing_items for name in item.names}
    parsed_paths = extract_skill_listing_paths_from_xml(message.join_text_parts(message_item.parts))
    if not parsed_paths:
        return None

    filtered_paths = {name: path for name, path in parsed_paths.items() if name in listed_names}
    if not filtered_paths:
        return None

    return filtered_paths, any(item.incremental for item in listing_items)


def _restore_available_skill_paths_from_history(session: Session) -> dict[str, str]:
    restored_paths: dict[str, str] = {}
    for item in session.conversation_history:
        if not isinstance(item, message.DeveloperMessage):
            continue
        extracted = _extract_skill_listing_paths(item)
        if extracted is None:
            continue

        listed_paths, incremental = extracted
        if incremental:
            restored_paths.update(listed_paths)
        else:
            restored_paths = dict(listed_paths)

    if not restored_paths:
        return {}

    _mark_system_skill_listing_loaded(session, restored_paths)
    return restored_paths


def _load_cached_skill_listing_paths(cached_content: str | None) -> dict[str, str] | None:
    if not cached_content:
        return None
    try:
        loaded = json.loads(cached_content)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None

    loaded_dict = cast(dict[object, object], loaded)
    return {str(name): str(path) for name, path in loaded_dict.items()}


def _get_available_skill_paths_by_name(session: Session) -> dict[str, str]:
    status = session.file_tracker.get(_get_system_skill_listing_marker_path(session))
    if status is None or not status.is_skill_listing:
        return {}
    if status.skill_listing_paths_by_name is not None:
        return dict(status.skill_listing_paths_by_name)

    cached_paths = _load_cached_skill_listing_paths(status.cached_content)
    if cached_paths is not None:
        return cached_paths
    return _restore_available_skill_paths_from_history(session)


def _mark_system_skill_listing_loaded(session: Session, skill_paths_by_name: dict[str, str]) -> None:
    marker_path = _get_system_skill_listing_marker_path(session)
    existing = session.file_tracker.get(marker_path)
    serialized_state = json.dumps(skill_paths_by_name, sort_keys=True)
    session.file_tracker[marker_path] = FileStatus(
        mtime=0.0,
        content_sha256=hash_text_sha256(serialized_state),
        is_memory=existing.is_memory if existing else False,
        is_skill=existing.is_skill if existing else False,
        is_skill_listing=True,
        skill_listing_paths_by_name=dict(skill_paths_by_name),
        skill_attachment_source=existing.skill_attachment_source if existing else None,
        is_directory=existing.is_directory if existing else False,
        read_complete=existing.read_complete if existing else False,
    )


def get_available_skills_for_session(session: Session) -> list[Skill]:
    install_system_skills()
    loader = SkillLoader()
    loader.discover_skills(work_dir=session.work_dir)
    return list(loader.loaded_skills.values())


def _collect_skill_blocks(session: Session, skills: list[Skill], *, explicit: bool) -> tuple[list[str], list[Skill]]:
    skill_blocks: list[str] = []
    activated_skills: list[Skill] = []
    loaded_dynamic_paths_by_name = _get_loaded_skill_paths_by_name(session, dynamic_only=True)
    loaded_all_paths_by_name = _get_loaded_skill_paths_by_name(session, dynamic_only=False)

    for skill in skills:
        skill_content = _read_skill_content(skill)
        if skill_content is None:
            continue

        skill_path = str(skill.skill_path)
        if explicit and _is_skill_content_already_in_context(session, skill_path):
            _mark_skill_loaded(session, skill_path, skill_content, source="explicit")
            loaded_dynamic_paths_by_name[skill.name] = skill_path
            loaded_all_paths_by_name[skill.name] = skill_path
            skill_blocks.append(_fmt_skill_already_in_context(skill.name, skill_path, tools.READ))
            activated_skills.append(skill)
            continue

        if not explicit:
            non_dynamic_path = loaded_all_paths_by_name.get(skill.name)
            dynamic_path = loaded_dynamic_paths_by_name.get(skill.name)
            if non_dynamic_path is not None and non_dynamic_path != dynamic_path:
                continue
            if dynamic_path == skill_path and is_tracked_file_unchanged(session, skill_path):
                continue

        _mark_skill_loaded(session, skill_path, skill_content, source="explicit" if explicit else "dynamic")
        loaded_dynamic_paths_by_name[skill.name] = skill_path
        loaded_all_paths_by_name[skill.name] = skill_path
        skill_blocks.append(_format_skill_block_str(skill, skill_content, explicit=explicit))
        activated_skills.append(skill)

    return skill_blocks, activated_skills


def _collect_dynamic_skills(session: Session, skills: list[Skill]) -> list[Skill]:
    activated_skills: list[Skill] = []
    loaded_dynamic_paths_by_name = _get_loaded_skill_paths_by_name(session, dynamic_only=True)
    loaded_all_paths_by_name = _get_loaded_skill_paths_by_name(session, dynamic_only=False)

    for skill in skills:
        skill_content = _read_skill_content(skill)
        if skill_content is None:
            continue

        skill_path = str(skill.skill_path)
        non_dynamic_path = loaded_all_paths_by_name.get(skill.name)
        dynamic_path = loaded_dynamic_paths_by_name.get(skill.name)
        if non_dynamic_path is not None and non_dynamic_path != dynamic_path:
            continue
        if dynamic_path == skill_path and is_tracked_file_unchanged(session, skill_path):
            continue

        _mark_skill_loaded(session, skill_path, skill_content, source="dynamic")
        loaded_dynamic_paths_by_name[skill.name] = skill_path
        loaded_all_paths_by_name[skill.name] = skill_path
        activated_skills.append(skill)

    return activated_skills


def _build_skill_attachment(
    session: Session, skills: list[Skill], *, explicit: bool
) -> message.DeveloperMessage | None:
    skill_blocks, activated_skills = _collect_skill_blocks(session, skills, explicit=explicit)
    if not skill_blocks:
        return None

    ui_items: list[DeveloperUIItem] = [SkillActivatedUIItem(name=skill.name) for skill in activated_skills]
    return message.DeveloperMessage(
        parts=message.text_parts_from_str(f"<system-reminder>{chr(10).join(skill_blocks)}\n</system-reminder>"),
        ui_extra=DeveloperUIExtra(items=ui_items),
    )


def build_dynamic_skill_listing_attachment(session: Session, skills: list[Skill]) -> message.DeveloperMessage | None:
    activated_skills = _collect_dynamic_skills(session, skills)
    if not activated_skills:
        return None

    content = _format_dynamic_available_skills_str(activated_skills)
    ui_items: list[DeveloperUIItem] = [SkillDiscoveredUIItem(name=skill.name) for skill in activated_skills]
    return message.DeveloperMessage(
        parts=message.text_parts_from_str(f"<system-reminder>{content}\n</system-reminder>"),
        ui_extra=DeveloperUIExtra(items=ui_items),
    )


async def available_skills_attachment_for(
    session: Session,
    *,
    get_available_skills_for_session_fn: Callable[[Session], list[Skill]],
) -> message.DeveloperMessage | None:
    """Attach the available-skill listing and re-announce static skills when metadata changes."""

    skills = _sort_skills_for_listing(get_available_skills_for_session_fn(session))
    if not skills:
        return None

    previous_skill_paths = _get_available_skill_paths_by_name(session)
    current_skill_paths = {skill.name: str(skill.skill_path) for skill in skills}
    updated_skills = [
        skill for skill in skills if previous_skill_paths.get(skill.name) != current_skill_paths[skill.name]
    ]
    if not updated_skills:
        return None

    _mark_system_skill_listing_loaded(session, current_skill_paths)
    content = (
        _fmt_available_skills_added(_build_skills_xml(updated_skills))
        if previous_skill_paths
        else format_available_skills_str(skills)
    )
    return message.DeveloperMessage(
        parts=message.text_parts_from_str(f"<system-reminder>{content}\n</system-reminder>"),
        attachment_position="prepend",
        ui_extra=DeveloperUIExtra(
            items=[
                SkillListingUIItem(
                    names=[skill.name for skill in updated_skills], incremental=bool(previous_skill_paths)
                )
            ]
        ),
    )


async def available_skills_attachment(session: Session) -> message.DeveloperMessage | None:
    return await available_skills_attachment_for(
        session,
        get_available_skills_for_session_fn=get_available_skills_for_session,
    )


async def skill_attachment_for(
    session: Session,
    *,
    resolve_skill_for_input_fn: Callable[[Session, str], Skill | None],
) -> message.DeveloperMessage | None:
    """Load skill content when user references skills with explicit skill syntax."""

    skill_names = get_skills_from_user_input(session)
    if not skill_names:
        return None

    resolved_skills: list[Skill] = []
    seen_paths: set[str] = set()
    for skill_name in skill_names:
        skill = resolve_skill_for_input_fn(session, skill_name)
        if skill is None:
            continue
        skill_path = str(skill.skill_path)
        if skill_path in seen_paths:
            continue
        seen_paths.add(skill_path)
        resolved_skills.append(skill)

    return _build_skill_attachment(session, resolved_skills, explicit=True)


async def skill_attachment(session: Session) -> message.DeveloperMessage | None:
    return await skill_attachment_for(session, resolve_skill_for_input_fn=resolve_skill_for_input)


async def last_path_skill_attachment(session: Session) -> message.DeveloperMessage | None:
    """Announce nested project-local skills discovered near accessed paths."""

    dynamic_skills = _get_dynamic_skills_for_session(session)
    if not dynamic_skills:
        return None
    return build_dynamic_skill_listing_attachment(session, dynamic_skills)
