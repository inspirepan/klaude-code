"""Dynamic prompt synchronization from OpenAI Codex GitHub repository."""

import json
import time
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import httpx

from klaude_code.log import DebugType, log_debug

GITHUB_API_RELEASES = "https://api.github.com/repos/openai/codex/releases/latest"
GITHUB_HTML_RELEASES = "https://github.com/openai/codex/releases/latest"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/openai/codex"

CACHE_DIR = Path.home() / ".klaude" / "codex-prompts"
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours

type ModelFamily = Literal["gpt-5.2-codex", "codex-max", "codex", "gpt-5.2", "gpt-5.1"]

PROMPT_FILES: dict[ModelFamily, str] = {
    "gpt-5.2-codex": "gpt-5.2-codex_prompt.md",
    "codex-max": "gpt-5.1-codex-max_prompt.md",
    "codex": "gpt_5_codex_prompt.md",
    "gpt-5.2": "gpt_5_2_prompt.md",
    "gpt-5.1": "gpt_5_1_prompt.md",
}

CACHE_FILES: dict[ModelFamily, str] = {
    "gpt-5.2-codex": "gpt-5.2-codex-instructions.md",
    "codex-max": "codex-max-instructions.md",
    "codex": "codex-instructions.md",
    "gpt-5.2": "gpt-5.2-instructions.md",
    "gpt-5.1": "gpt-5.1-instructions.md",
}


@cache
def _load_bundled_prompt(prompt_path: str) -> str:
    """Load bundled prompt from package resources."""
    return files("klaude_code.core").joinpath(prompt_path).read_text(encoding="utf-8").strip()


class CacheMetadata:
    def __init__(self, etag: str | None, tag: str, last_checked: int, url: str):
        self.etag = etag
        self.tag = tag
        self.last_checked = last_checked
        self.url = url

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "etag": self.etag,
            "tag": self.tag,
            "last_checked": self.last_checked,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CacheMetadata":
        etag = data.get("etag")
        last_checked = data.get("last_checked")
        return cls(
            etag=etag if isinstance(etag, str) else None,
            tag=str(data.get("tag", "")),
            last_checked=int(last_checked) if isinstance(last_checked, int | float) else 0,
            url=str(data.get("url", "")),
        )


def get_model_family(model: str) -> ModelFamily:
    """Determine model family from model name."""
    if "gpt-5.2-codex" in model or "gpt 5.2 codex" in model:
        return "gpt-5.2-codex"
    if "codex-max" in model:
        return "codex-max"
    if "codex" in model or model.startswith("codex-"):
        return "codex"
    if "gpt-5.2" in model:
        return "gpt-5.2"
    return "gpt-5.1"


def _get_latest_release_tag(client: httpx.Client) -> str:
    """Get latest release tag from GitHub."""
    try:
        response = client.get(GITHUB_API_RELEASES)
        if response.status_code == 200:
            data: dict[str, Any] = response.json()
            tag_name: Any = data.get("tag_name")
            if isinstance(tag_name, str):
                return tag_name
    except httpx.HTTPError:
        pass

    # Fallback: follow redirect from releases/latest
    response = client.get(GITHUB_HTML_RELEASES, follow_redirects=True)
    if response.status_code == 200:
        final_url = str(response.url)
        if "/tag/" in final_url:
            parts = final_url.split("/tag/")
            if len(parts) > 1 and "/" not in parts[-1]:
                return parts[-1]

    raise RuntimeError("Failed to determine latest release tag from GitHub")


def _load_cache_metadata(meta_file: Path) -> CacheMetadata | None:
    if not meta_file.exists():
        return None
    try:
        data = json.loads(meta_file.read_text())
        return CacheMetadata.from_dict(data)
    except (json.JSONDecodeError, ValueError):
        return None


def _save_cache_metadata(meta_file: Path, metadata: CacheMetadata) -> None:
    meta_file.parent.mkdir(parents=True, exist_ok=True)
    meta_file.write_text(json.dumps(metadata.to_dict(), indent=2))


def get_codex_instructions(model: str = "gpt-5.1-codex", force_refresh: bool = False) -> str:
    """Get Codex instructions for the given model.

    Args:
        model: Model name to get instructions for.
        force_refresh: If True, bypass cache TTL and fetch fresh instructions.

    Returns:
        The Codex system prompt instructions.
    """
    model_family = get_model_family(model)
    prompt_file = PROMPT_FILES[model_family]
    cache_file = CACHE_DIR / CACHE_FILES[model_family]
    meta_file = CACHE_DIR / f"{CACHE_FILES[model_family].replace('.md', '-meta.json')}"

    # Check cache unless force refresh
    if not force_refresh:
        metadata = _load_cache_metadata(meta_file)
        if metadata and cache_file.exists():
            age = int(time.time()) - metadata.last_checked
            if age < CACHE_TTL_SECONDS:
                log_debug(f"Using cached {model_family} instructions (age: {age}s)", debug_type=DebugType.GENERAL)
                return cache_file.read_text()

    try:
        with httpx.Client(timeout=30.0) as client:
            latest_tag = _get_latest_release_tag(client)
            instructions_url = f"{GITHUB_RAW_BASE}/{latest_tag}/codex-rs/core/{prompt_file}"

            # Load existing metadata for conditional request
            metadata = _load_cache_metadata(meta_file)
            headers: dict[str, str] = {}

            # Only use ETag if tag matches (different release = different content)
            if metadata and metadata.tag == latest_tag and metadata.etag:
                headers["If-None-Match"] = metadata.etag

            response = client.get(instructions_url, headers=headers)

            if response.status_code == 304 and cache_file.exists():
                # Not modified, update last_checked and return cached
                if metadata:
                    metadata.last_checked = int(time.time())
                    _save_cache_metadata(meta_file, metadata)
                log_debug(f"Codex {model_family} instructions not modified", debug_type=DebugType.GENERAL)
                return cache_file.read_text()

            if response.status_code == 200:
                instructions = response.text
                new_etag = response.headers.get("etag")

                # Save to cache
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(instructions)
                _save_cache_metadata(
                    meta_file,
                    CacheMetadata(
                        etag=new_etag,
                        tag=latest_tag,
                        last_checked=int(time.time()),
                        url=instructions_url,
                    ),
                )

                log_debug(f"Updated {model_family} instructions from GitHub", debug_type=DebugType.GENERAL)
                return instructions

            raise RuntimeError(f"HTTP {response.status_code}")

    except Exception as e:
        log_debug(f"Failed to fetch {model_family} instructions: {e}", debug_type=DebugType.GENERAL)

        # Fallback to cached version
        if cache_file.exists():
            log_debug(f"Using cached {model_family} instructions (fallback)", debug_type=DebugType.GENERAL)
            return cache_file.read_text()

        # Last resort: use bundled prompt
        bundled_path = _get_bundled_prompt_path(model_family)
        if bundled_path:
            log_debug(f"Using bundled {model_family} instructions (fallback)", debug_type=DebugType.GENERAL)
            return _load_bundled_prompt(bundled_path)

        raise RuntimeError(f"No Codex instructions available for {model_family}") from e


def _get_bundled_prompt_path(model_family: ModelFamily) -> str | None:
    """Get bundled prompt path for model family."""
    if model_family == "gpt-5.2-codex":
        return "prompts/prompt-codex-gpt-5-2-codex.md"
    if model_family == "gpt-5.2":
        return "prompts/prompt-codex-gpt-5-2.md"
    if model_family in ("codex", "codex-max", "gpt-5.1"):
        return "prompts/prompt-codex.md"
    return None


def invalidate_cache(model: str | None = None) -> None:
    """Invalidate cached instructions to force refresh on next access.

    Args:
        model: If provided, only invalidate cache for this model's family.
               If None, invalidate all cached instructions.
    """
    if model:
        model_family = get_model_family(model)
        meta_file = CACHE_DIR / f"{CACHE_FILES[model_family].replace('.md', '-meta.json')}"
        if meta_file.exists():
            meta_file.unlink()
    else:
        if CACHE_DIR.exists():
            for meta_file in CACHE_DIR.glob("*-meta.json"):
                meta_file.unlink()
