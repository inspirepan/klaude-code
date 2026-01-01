from __future__ import annotations

from typing import Any, cast

from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

IMAGE_GEN_DESCRIPTION = """\
Generate one or more images from a text prompt.

This tool invokes an Image Gen model to generate images. The generated image paths are automatically \
returned in the response.

Inputs:
- `prompt`: The main instruction describing the desired image.
- `image_paths` (optional): Local image file paths to use as references for editing or style guidance.
- `generation` (optional): Per-call image generation settings (aspect ratio / size).

Notes:
- Provide a short textual description of the generated image(s).
- Do NOT include base64 image data in text output.
- When providing multiple input images, describe each image's characteristics and purpose in the prompt, \
not just "image 1, image 2" - the image model cannot distinguish image order. \
For example: "Edit the first image (a photo of a cat sitting on a windowsill) to match the style of \
the second image (Van Gogh's Starry Night painting with swirling blue brushstrokes)."

Multi-turn image editing:
- Use `resume` to continue editing a previously generated image. The agent preserves its full context \
including the generated image, so you don't need to pass `image_paths` again.
- Example workflow:
  1. Call ImageGen with prompt="Generate a watercolor painting of a mountain lake" -> returns agent_id
  2. Call ImageGen with resume=agent_id, prompt="Add a wooden cabin on the shore" -> edits the previous image
  3. Call ImageGen with resume=agent_id, prompt="Change to sunset lighting" -> continues editing

- Agents can be resumed using the `resume` parameter by passing the agent ID from a previous invocation. When resumed, the agent
continues with its full previous context preserved. When NOT resuming, each invocation starts fresh and you should provide a detailed
task description with all necessary context.
- When the agent is done, it will return a single message back to you along with its agent ID. You can use this ID to resume the agent
later if needed for follow-up work.

"""


IMAGE_GEN_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "resume": {
            "type": "string",
            "description": "Optional agent ID to resume from. If provided, the agent will continue from the previous execution transcript.",
        },
        "description": {
            "type": "string",
            "description": "A short (3-5 word) description of the request.",
        },
        "prompt": {
            "type": "string",
            "description": "Text prompt for image generation.",
        },
        "image_paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional local image file paths used as references.",
        },
        "generation": {
            "type": "object",
            "description": "Optional per-call image generation settings.",
            "properties": {
                "aspect_ratio": {
                    "type": "string",
                    "description": "Aspect ratio, e.g. '16:9', '1:1', '9:16'.",
                },
                "image_size": {
                    "type": "string",
                    "enum": ["1K", "2K", "4K"],
                    "description": "Output size for Nano Banana Pro (must use uppercase K).",
                },
                "extra": {
                    "type": "object",
                    "description": "Provider/model-specific extra parameters (future-proofing).",
                },
            },
            "additionalProperties": False,
        },
    },
    "required": ["prompt"],
    "additionalProperties": False,
}


def _quote_at_pattern_path(path: str) -> str:
    if any(ch.isspace() for ch in path) or '"' in path:
        escaped = path.replace('"', '\\"')
        return f'@"{escaped}"'
    return f"@{path}"


def _build_image_gen_prompt(args: dict[str, Any]) -> str:
    prompt = str(args.get("prompt") or "").strip()
    image_paths = args.get("image_paths")

    lines: list[str] = []
    if prompt:
        lines.append(prompt)

    if isinstance(image_paths, list) and image_paths:
        referenced = [str(p) for p in cast(list[object], image_paths) if str(p).strip()]
        if referenced:
            lines.append("\n# Reference images\n" + "\n".join(_quote_at_pattern_path(p) for p in referenced))

    lines.append("\nReturn a short description of the generated image(s).")
    return "\n".join(lines).strip()


register_sub_agent(
    SubAgentProfile(
        name="ImageGen",
        description=IMAGE_GEN_DESCRIPTION,
        parameters=IMAGE_GEN_PARAMETERS,
        prompt_file="prompts/prompt-sub-agent-image-gen.md",
        tool_set=(),
        prompt_builder=_build_image_gen_prompt,
        active_form="Generating Image",
    )
)
