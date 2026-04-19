from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/skills", tags=["skills"])

class SkillItem(BaseModel):
    name: str
    description: str
    location: str

class SkillsResponse(BaseModel):
    items: list[SkillItem]

@router.get("")
async def list_skills(
    raw_work_dir: str | None = Query(None, alias="work_dir"),
) -> SkillsResponse:
    try:
        if raw_work_dir and raw_work_dir.strip():
            from klaude_code.skill import get_available_skills_for_work_dir

            skills = get_available_skills_for_work_dir(Path(raw_work_dir.strip()))
        else:
            from klaude_code.skill import get_available_skills

            skills = get_available_skills()
    except (ImportError, RuntimeError):
        skills = []

    return SkillsResponse(items=[SkillItem(name=name, description=desc, location=loc) for name, desc, loc in skills])
