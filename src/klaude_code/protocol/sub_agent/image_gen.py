from __future__ import annotations

from typing import Any, cast

from klaude_code.protocol.sub_agent import AVAILABILITY_IMAGE_MODEL, SubAgentProfile, register_sub_agent


def _quote_at_pattern_path(path: str) -> str:
    if any(ch.isspace() for ch in path) or '"' in path:
        escaped = path.replace('"', '\\"')
        return f'@"{escaped}"'
    return f"@{path}"


def build_image_gen_prompt(args: dict[str, Any]) -> str:
    prompt = str(args.get("prompt") or "").strip()
    image_paths = args.get("image_paths")

    lines: list[str] = ["Generate images: " + prompt]
    if isinstance(image_paths, list) and image_paths:
        referenced = [str(p) for p in cast(list[object], image_paths) if str(p).strip()]
        if referenced:
            lines.append("\n# Reference images\n" + "\n".join(_quote_at_pattern_path(p) for p in referenced))

    return "\n".join(lines).strip()


register_sub_agent(
    SubAgentProfile(
        name="ImageGen",
        prompt_file="prompts/prompt-sub-agent-image-gen.md",
        tool_set=(),
        prompt_builder=build_image_gen_prompt,
        active_form="Generating Image",
        availability_requirement=AVAILABILITY_IMAGE_MODEL,
        standalone_tool=True,
    )
)
