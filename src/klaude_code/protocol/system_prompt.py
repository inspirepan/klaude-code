SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"


def split_system_prompt_for_cache(system_prompt: str | None) -> tuple[str | None, str | None]:
    """Split a system prompt into static and dynamic sections for cache-aware clients."""

    if not system_prompt:
        return None, None

    static_part, marker, dynamic_part = system_prompt.partition(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
    if not marker:
        return system_prompt, None

    static_text = static_part.rstrip("\n") or None
    dynamic_text = dynamic_part.lstrip("\n") or None
    return static_text, dynamic_text


def strip_system_prompt_boundary(system_prompt: str | None) -> str | None:
    """Remove the internal cache boundary marker before sending text to providers."""

    static_part, dynamic_part = split_system_prompt_for_cache(system_prompt)
    if static_part and dynamic_part:
        return static_part + "\n\n" + dynamic_part
    return static_part or dynamic_part
