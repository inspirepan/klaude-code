from __future__ import annotations

from fastapi import APIRouter

from klaude_code.config import load_config

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/models")
async def list_models() -> dict[str, list[dict[str, str | bool]]]:
    config = load_config()
    entries = config.iter_model_entries(only_available=False, include_disabled=False)
    default_model = (config.main_model or "").strip()
    models = [
        {
            "name": entry.selector,
            "is_default": entry.selector == default_model or entry.model_name == default_model,
        }
        for entry in entries
    ]
    return {"models": models}
