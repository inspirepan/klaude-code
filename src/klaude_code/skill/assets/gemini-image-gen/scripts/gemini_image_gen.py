#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "google-genai>=1.0.0",
#     "google-auth>=2.0.0",
#     "pillow>=10.0.0",
# ]
# ///
"""Generate or edit images with the Google Gemini Image API (Nano Banana).

Supports text-to-image generation, image editing with up to 14 reference images,
Google Search grounding, and up to 4K resolution output.

Authentication (auto-detected, checked in order):
  1. GEMINI_API_KEY                          Google AI Studio API key
  2. GOOGLE_APPLICATION_CREDENTIALS +        Vertex AI service account
     GOOGLE_CLOUD_PROJECT +
     GOOGLE_CLOUD_LOCATION

Models:
  gemini-2.5-flash-image         Fast, low-latency (default)
  gemini-3-pro-image-preview     Professional: 4K, text rendering, Search, Thinking

Examples:
  # Generate a simple image (API key)
  uv run gemini_image_gen.py generate --prompt "A cozy alpine cabin at dawn"

  # Generate via Vertex AI (auto-detected from env vars)
  uv run gemini_image_gen.py generate --prompt "A cozy alpine cabin at dawn"

  # Generate with Pro model and 4K
  uv run gemini_image_gen.py generate \\
    --prompt "Da Vinci anatomical sketch of a butterfly" \\
    --model gemini-3-pro-image-preview --resolution 4K

  # Edit an image
  uv run gemini_image_gen.py edit \\
    --prompt "Replace the background with a sunset" --image input.png

  # Multi-image composition (up to 14 images)
  uv run gemini_image_gen.py edit \\
    --prompt "Group photo of these people" \\
    --image p1.png --image p2.png --image p3.png \\
    --model gemini-3-pro-image-preview --resolution 2K

  # Search-grounded generation
  uv run gemini_image_gen.py generate \\
    --prompt "Current weather forecast for Tokyo as a chart" \\
    --model gemini-3-pro-image-preview --google-search
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "gemini-2.5-flash-image"
DEFAULT_ASPECT_RATIO = "1:1"
DEFAULT_RESOLUTION = "1K"

ALLOWED_ASPECT_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
ALLOWED_RESOLUTIONS = {"1K", "2K", "4K"}
PRO_MODEL = "gemini-3-pro-image-preview"
MAX_INPUT_IMAGES = 14

_GOOGLE_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def _die(message: str, code: int = 1) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)


def _warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def _detect_auth_mode(dry_run: bool) -> str:
    """Detect authentication mode. Returns 'api_key', 'vertex', or 'none'."""
    if os.getenv("GEMINI_API_KEY"):
        print("Auth: GEMINI_API_KEY detected.", file=sys.stderr)
        return "api_key"
    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION")
    if creds and project and location:
        print(f"Auth: Vertex AI detected (project={project}, location={location}).", file=sys.stderr)
        return "vertex"
    if dry_run:
        _warn("No credentials detected; dry-run only.")
        return "none"
    _die(
        "No credentials found. Set one of:\n"
        "  Option 1 (API key):  export GEMINI_API_KEY='your-key'\n"
        "                       Get one at: https://aistudio.google.com/apikey\n"
        "  Option 2 (Vertex):   export GOOGLE_APPLICATION_CREDENTIALS='/path/to/sa-key.json'\n"
        "                       export GOOGLE_CLOUD_PROJECT='your-project-id'\n"
        "                       export GOOGLE_CLOUD_LOCATION='us-central1'"
    )
    return "none"


def _read_prompt(prompt: str | None, prompt_file: str | None) -> str:
    if prompt and prompt_file:
        _die("Use --prompt or --prompt-file, not both.")
    if prompt_file:
        path = Path(prompt_file)
        if not path.exists():
            _die(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8").strip()
    if prompt:
        return prompt.strip()
    _die("Missing prompt. Use --prompt or --prompt-file.")
    return ""


def _check_image_paths(paths: list[str] | None) -> list[Path]:
    if not paths:
        return []
    if len(paths) > MAX_INPUT_IMAGES:
        _die(f"Too many input images ({len(paths)}). Maximum is {MAX_INPUT_IMAGES}.")
    resolved: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            _die(f"Image file not found: {path}")
        resolved.append(path)
    return resolved


def _validate_aspect_ratio(ratio: str) -> None:
    if ratio not in ALLOWED_ASPECT_RATIOS:
        _die(f"aspect-ratio must be one of: {', '.join(sorted(ALLOWED_ASPECT_RATIOS))}")


def _validate_resolution(resolution: str, model: str) -> None:
    if resolution not in ALLOWED_RESOLUTIONS:
        _die(f"resolution must be one of: {', '.join(sorted(ALLOWED_RESOLUTIONS))}")
    if resolution != "1K" and model != PRO_MODEL:
        _warn(f"Resolution {resolution} is only supported by {PRO_MODEL}. Switching model.")


def _auto_detect_resolution(image_paths: list[Path], explicit_resolution: str) -> str:
    if explicit_resolution != DEFAULT_RESOLUTION:
        return explicit_resolution
    if not image_paths:
        return explicit_resolution

    try:
        from PIL import Image as PILImage
    except ImportError:
        return explicit_resolution

    max_dim = 0
    for p in image_paths:
        try:
            with PILImage.open(p) as img:
                w, h = img.size
                max_dim = max(max_dim, w, h)
        except Exception:
            continue

    if max_dim >= 3000:
        resolution = "4K"
    elif max_dim >= 1500:
        resolution = "2K"
    else:
        return explicit_resolution

    print(f"Auto-detected resolution: {resolution} (from max input dimension {max_dim})", file=sys.stderr)
    return resolution


def _augment_prompt(args: argparse.Namespace, prompt: str) -> str:
    if not args.augment:
        return prompt

    sections: list[str] = []
    if args.use_case:
        sections.append(f"Use case: {args.use_case}")
    sections.append(f"Primary request: {prompt}")
    if args.scene:
        sections.append(f"Scene/background: {args.scene}")
    if args.subject:
        sections.append(f"Subject: {args.subject}")
    if args.style:
        sections.append(f"Style/medium: {args.style}")
    if args.composition:
        sections.append(f"Composition/framing: {args.composition}")
    if args.lighting:
        sections.append(f"Lighting/mood: {args.lighting}")
    if args.palette:
        sections.append(f"Color palette: {args.palette}")
    if args.text:
        sections.append(f'Text (verbatim): "{args.text}"')
    if args.constraints:
        sections.append(f"Constraints: {args.constraints}")
    if args.negative:
        sections.append(f"Avoid: {args.negative}")

    return "\n".join(sections)


def _build_config(args: argparse.Namespace) -> dict[str, Any]:
    from google.genai import types

    modalities = ["Image"] if args.image_only else ["TEXT", "IMAGE"]

    image_config_kwargs: dict[str, Any] = {}
    if args.aspect_ratio != DEFAULT_ASPECT_RATIO:
        image_config_kwargs["aspect_ratio"] = args.aspect_ratio
    if args.model == PRO_MODEL and args.resolution != DEFAULT_RESOLUTION:
        image_config_kwargs["image_size"] = args.resolution

    config_kwargs: dict[str, Any] = {
        "response_modalities": modalities,
    }
    if image_config_kwargs:
        config_kwargs["image_config"] = types.ImageConfig(**image_config_kwargs)
    if args.google_search:
        config_kwargs["tools"] = [{"google_search": {}}]

    return config_kwargs


def _create_client(auth_mode: str):
    from google import genai

    if auth_mode == "vertex":
        from google.auth import load_credentials_from_file

        creds_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ["GOOGLE_CLOUD_LOCATION"]

        credentials, _ = load_credentials_from_file(
            creds_path,
            scopes=[_GOOGLE_CLOUD_PLATFORM_SCOPE],
        )
        return genai.Client(
            vertexai=True,
            credentials=credentials,
            project=project,
            location=location,
        )

    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _save_response_images(response: Any, out_path: Path, force: bool) -> list[Path]:
    from PIL import Image as PILImage

    saved: list[Path] = []
    image_idx = 0

    for part in response.parts:
        if part.text is not None:
            print(f"Model: {part.text}")
        elif part.inline_data is not None:
            image_idx += 1
            if image_idx == 1:
                target = out_path
            else:
                target = out_path.with_name(f"{out_path.stem}-{image_idx}{out_path.suffix}")

            if target.exists() and not force:
                _die(f"Output already exists: {target} (use --force to overwrite)")

            target.parent.mkdir(parents=True, exist_ok=True)

            # part.inline_data.data is raw bytes from the SDK
            image_data = part.inline_data.data
            if isinstance(image_data, str):
                import base64
                image_data = base64.b64decode(image_data)

            image = PILImage.open(BytesIO(image_data))

            # Save as PNG
            if image.mode == "RGBA":
                rgb = PILImage.new("RGB", image.size, (255, 255, 255))
                rgb.paste(image, mask=image.split()[3])
                rgb.save(str(target), "PNG")
            elif image.mode == "RGB":
                image.save(str(target), "PNG")
            else:
                image.convert("RGB").save(str(target), "PNG")

            print(f"Wrote {target}")
            saved.append(target)

    return saved


def _generate(args: argparse.Namespace) -> None:
    prompt = _read_prompt(args.prompt, args.prompt_file)
    prompt = _augment_prompt(args, prompt)

    _validate_aspect_ratio(args.aspect_ratio)
    if args.model == PRO_MODEL:
        _validate_resolution(args.resolution, args.model)

    if args.google_search and args.model != PRO_MODEL:
        _warn(f"Google Search grounding works best with {PRO_MODEL}. Consider switching.")

    out_path = Path(args.out)
    if out_path.suffix == "":
        out_path = out_path.with_suffix(".png")

    payload_preview = {
        "model": args.model,
        "prompt": prompt,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution if args.model == PRO_MODEL else "N/A (Flash)",
        "image_only": args.image_only,
        "google_search": args.google_search,
        "output": str(out_path),
    }

    if args.dry_run:
        print(json.dumps(payload_preview, indent=2, ensure_ascii=False))
        return

    auth_mode = _detect_auth_mode(dry_run=False)

    from google.genai import types

    config_kwargs = _build_config(args)

    print(f"Calling Gemini API ({args.model}). This may take a moment...", file=sys.stderr)
    started = time.time()

    client = _create_client(auth_mode)
    response = client.models.generate_content(
        model=args.model,
        contents=[prompt],
        config=types.GenerateContentConfig(**config_kwargs),
    )

    elapsed = time.time() - started
    print(f"Generation completed in {elapsed:.1f}s.", file=sys.stderr)

    saved = _save_response_images(response, out_path, args.force)
    if not saved:
        _die("No image was generated in the response. Try rephrasing the prompt.")


def _edit(args: argparse.Namespace) -> None:
    prompt = _read_prompt(args.prompt, args.prompt_file)
    prompt = _augment_prompt(args, prompt)

    image_paths = _check_image_paths(args.image)
    if not image_paths:
        _die("edit requires at least one --image.")

    _validate_aspect_ratio(args.aspect_ratio)

    # Auto-detect resolution for Pro model
    if args.model == PRO_MODEL:
        args.resolution = _auto_detect_resolution(image_paths, args.resolution)
        _validate_resolution(args.resolution, args.model)

    out_path = Path(args.out)
    if out_path.suffix == "":
        out_path = out_path.with_suffix(".png")

    payload_preview = {
        "model": args.model,
        "prompt": prompt,
        "input_images": [str(p) for p in image_paths],
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution if args.model == PRO_MODEL else "N/A (Flash)",
        "image_only": args.image_only,
        "google_search": args.google_search,
        "output": str(out_path),
    }

    if args.dry_run:
        print(json.dumps(payload_preview, indent=2, ensure_ascii=False))
        return

    auth_mode = _detect_auth_mode(dry_run=False)

    from google.genai import types
    from PIL import Image as PILImage

    config_kwargs = _build_config(args)

    # Build contents: images first, then prompt (as per Gemini API convention)
    pil_images = []
    for p in image_paths:
        pil_images.append(PILImage.open(p))

    contents: list[Any] = [*pil_images, prompt]

    print(
        f"Calling Gemini API ({args.model}) with {len(image_paths)} image(s)...",
        file=sys.stderr,
    )
    started = time.time()

    client = _create_client(auth_mode)
    response = client.models.generate_content(
        model=args.model,
        contents=contents,
        config=types.GenerateContentConfig(**config_kwargs),
    )

    elapsed = time.time() - started
    print(f"Edit completed in {elapsed:.1f}s.", file=sys.stderr)

    saved = _save_response_images(response, out_path, args.force)
    if not saved:
        _die("No image was generated in the response. Try rephrasing the prompt.")

    # Close PIL images
    for img in pil_images:
        img.close()


def _add_shared_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        choices=[DEFAULT_MODEL, PRO_MODEL],
        help=f"Model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--prompt", "-p",
        help="Text prompt for image generation/editing",
    )
    parser.add_argument(
        "--prompt-file",
        metavar="FILE",
        help="Read prompt from a file (mutually exclusive with --prompt)",
    )
    parser.add_argument(
        "--aspect-ratio", "-a",
        default=DEFAULT_ASPECT_RATIO,
        metavar="RATIO",
        help=f"Output aspect ratio (default: {DEFAULT_ASPECT_RATIO}). "
             f"Options: {', '.join(sorted(ALLOWED_ASPECT_RATIOS))}",
    )
    parser.add_argument(
        "--resolution", "-r",
        default=DEFAULT_RESOLUTION,
        choices=sorted(ALLOWED_RESOLUTIONS),
        help=f"Output resolution, Pro model only (default: {DEFAULT_RESOLUTION}). Must be uppercase K.",
    )
    parser.add_argument(
        "--image-only",
        action="store_true",
        help="Only return image output, no accompanying text",
    )
    parser.add_argument(
        "--google-search",
        action="store_true",
        help="Enable Google Search grounding (best with Pro model)",
    )
    parser.add_argument(
        "--out", "-o",
        default="output.png",
        metavar="PATH",
        help="Output file path (default: output.png)",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing output files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the request payload without calling the API",
    )

    # Prompt augmentation
    aug_group = parser.add_argument_group("prompt augmentation")
    aug_group.add_argument(
        "--augment",
        dest="augment",
        action="store_true",
        default=True,
        help="Enable prompt augmentation (default: on)",
    )
    aug_group.add_argument(
        "--no-augment",
        dest="augment",
        action="store_false",
        help="Disable prompt augmentation; use raw prompt as-is",
    )
    aug_group.add_argument("--use-case", metavar="SLUG", help="Use-case taxonomy slug")
    aug_group.add_argument("--scene", metavar="TEXT", help="Scene/background description")
    aug_group.add_argument("--subject", metavar="TEXT", help="Main subject description")
    aug_group.add_argument("--style", metavar="TEXT", help="Style/medium (photo, illustration, 3D, etc.)")
    aug_group.add_argument("--composition", metavar="TEXT", help="Composition/framing instructions")
    aug_group.add_argument("--lighting", metavar="TEXT", help="Lighting/mood description")
    aug_group.add_argument("--palette", metavar="TEXT", help="Color palette notes")
    aug_group.add_argument("--text", metavar="TEXT", help="Verbatim text to render in the image")
    aug_group.add_argument("--constraints", metavar="TEXT", help="Must-keep constraints")
    aug_group.add_argument("--negative", metavar="TEXT", help="Things to avoid in the output")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate or edit images via the Google Gemini Image API (Nano Banana).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""models:
  gemini-2.5-flash-image         Fast, low-latency generation (default)
  gemini-3-pro-image-preview     Professional: 4K, text rendering, Thinking, Search

examples:
  %(prog)s generate --prompt "A cozy alpine cabin at dawn"
  %(prog)s generate --prompt "Logo for The Daily Grind" --model gemini-3-pro-image-preview
  %(prog)s edit --prompt "Replace background with sunset" --image photo.png
  %(prog)s edit --prompt "Group photo of these people" -i p1.png -i p2.png -i p3.png
  %(prog)s generate --prompt "Weather forecast for Tokyo" --google-search -m gemini-3-pro-image-preview

authentication (auto-detected, checked in order):
  GEMINI_API_KEY                    Google AI Studio API key
  GOOGLE_APPLICATION_CREDENTIALS +  Vertex AI service account JSON key file
  GOOGLE_CLOUD_PROJECT +            GCP project ID (e.g. my-project-123)
  GOOGLE_CLOUD_LOCATION             GCP region (e.g. us-central1)
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate subcommand
    gen_parser = subparsers.add_parser(
        "generate",
        help="Create new image(s) from a text prompt",
        description="Generate images from text using the Gemini Image API.",
    )
    _add_shared_args(gen_parser)
    gen_parser.set_defaults(func=_generate)

    # edit subcommand
    edit_parser = subparsers.add_parser(
        "edit",
        help="Edit existing image(s) with text instructions",
        description="Edit images using text instructions. Supports up to 14 input images.",
    )
    _add_shared_args(edit_parser)
    edit_parser.add_argument(
        "--image", "-i",
        action="append",
        metavar="PATH",
        help="Input image path. Can be specified multiple times (up to 14 images).",
    )
    edit_parser.set_defaults(func=_edit)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
