from pathlib import Path

from klaude_code.agent.attachments.memory import get_existing_memory_paths_by_location
from klaude_code.agent.skill_inventory import (
    get_skill_names_by_location,
    get_skill_warnings_by_location,
    warmup_skill_inventory,
)
from klaude_code.protocol import events


def build_welcome_context_event(*, session_id: str, work_dir: Path) -> events.WelcomeContextEvent:
    """Build the deferred welcome context after skill discovery completes."""
    warmup_skill_inventory()
    return events.WelcomeContextEvent(
        session_id=session_id,
        work_dir=str(work_dir),
        loaded_skills=get_skill_names_by_location(),
        loaded_skill_warnings=get_skill_warnings_by_location(),
        loaded_memories=get_existing_memory_paths_by_location(work_dir=work_dir),
    )