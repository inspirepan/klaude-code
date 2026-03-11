from __future__ import annotations

from fastapi import APIRouter

from klaude_code.config import load_config
from klaude_code.config.formatters import format_model_params

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/models")
async def list_models() -> dict[str, list[dict[str, str | bool | list[str]]]]:
    config = load_config()
    entries = config.iter_model_entries(only_available=True, include_disabled=False)
    default_model = (config.main_model or "").strip()
    models = [
        {
            "name": entry.selector,
            "provider": entry.provider,
            "model_name": entry.model_name,
            "model_id": entry.model_id or entry.model_name,
            "params": format_model_params(entry),
            "is_default": entry.selector == default_model or entry.model_name == default_model,
        }
        for entry in entries
    ]
    return {"models": models}
