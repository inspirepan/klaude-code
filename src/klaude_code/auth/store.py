import json
from pathlib import Path
from typing import Any, cast


def load_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data: Any = json.loads(path.read_text())
    except ValueError:
        return {}
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def save_store(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def delete_store(path: Path) -> None:
    if path.exists():
        path.unlink()
