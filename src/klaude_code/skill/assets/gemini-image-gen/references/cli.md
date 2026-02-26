# CLI reference (`scripts/gemini_image_gen.py`)

## What this CLI does
- `generate`: create new images from a text prompt
- `edit`: edit existing images with text instructions (supports up to 14 input images)

Real API calls require **network access** + credentials (`GEMINI_API_KEY` or Vertex AI env vars). `--dry-run` does not.

## Authentication
The CLI auto-detects credentials in order:
1. `GEMINI_API_KEY` -- Google AI Studio API key
2. `GOOGLE_APPLICATION_CREDENTIALS` + `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION` -- Vertex AI

See `references/vertex-setup.md` for Vertex AI configuration details.

## Quick start

Dry-run (no API call, no network required):
```
uv run scripts/gemini_image_gen.py generate --prompt "Test" --dry-run
```

Generate (requires credentials + network):
```
uv run scripts/gemini_image_gen.py generate --prompt "A cozy alpine cabin at dawn"
```

## Guardrails
- Use the bundled CLI for all image generation/editing.
- Do **not** create one-off runner scripts unless the user explicitly asks.
- **Never modify** `scripts/gemini_image_gen.py`. Ask the user if something is missing.

## Commands

### generate
```
uv run scripts/gemini_image_gen.py generate \
  --prompt "A minimalist hero image of a ceramic coffee mug" \
  --model gemini-2.5-flash-image \
  --aspect-ratio 16:9 \
  --out output/hero.png
```

### edit
```
uv run scripts/gemini_image_gen.py edit \
  --prompt "Replace the background with a warm sunset gradient" \
  --image input.png \
  --out output/edited.png
```

Multi-image edit (up to 14 images):
```
uv run scripts/gemini_image_gen.py edit \
  --prompt "An office group photo of these people making funny faces" \
  --image person1.png --image person2.png --image person3.png \
  --model gemini-3-pro-image-preview \
  --resolution 2K \
  --aspect-ratio 5:4 \
  --out output/group.png
```

## Defaults (unless overridden)
- Model: `gemini-2.5-flash-image`
- Aspect ratio: `1:1`
- Resolution: `1K` (Pro model only; auto-detected from input images when editing)
- Response modalities: `TEXT,IMAGE`
- Output: `output.png`
- Augment: enabled (use `--no-augment` to skip)

## Key flags

| Flag | Values | Notes |
|---|---|---|
| `--model` | `gemini-2.5-flash-image`, `gemini-3-pro-image-preview` | Model selection |
| `--prompt` | text | Required. The generation/edit prompt |
| `--prompt-file` | path | Read prompt from file (mutually exclusive with --prompt) |
| `--image` | path | Input image(s) for editing. Repeatable, up to 14 |
| `--aspect-ratio` | `1:1`, `2:3`, `3:2`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `21:9` | Output aspect ratio |
| `--resolution` | `1K`, `2K`, `4K` | Output resolution (Pro model only) |
| `--image-only` | flag | Only return image, no text |
| `--google-search` | flag | Enable Google Search grounding |
| `--out` | path | Output file path (default: output.png) |
| `--force` | flag | Overwrite existing output |
| `--dry-run` | flag | Print request payload without calling API |
| `--augment` / `--no-augment` | flag | Enable/disable prompt augmentation |
| `--use-case` | text | Augmentation: use-case taxonomy slug |
| `--scene` | text | Augmentation: scene/background |
| `--subject` | text | Augmentation: main subject |
| `--style` | text | Augmentation: style/medium |
| `--composition` | text | Augmentation: composition/framing |
| `--lighting` | text | Augmentation: lighting/mood |
| `--palette` | text | Augmentation: color palette |
| `--text` | text | Augmentation: verbatim text to render |
| `--constraints` | text | Augmentation: must-keep constraints |
| `--negative` | text | Augmentation: things to avoid |

## Common recipes

Generate with augmentation fields:
```
uv run scripts/gemini_image_gen.py generate \
  --prompt "A minimal hero image of a ceramic coffee mug" \
  --use-case "landing page hero" \
  --style "clean product photography" \
  --composition "centered product, generous negative space" \
  --constraints "no logos, no text"
```

Generate with Pro model and 4K:
```
uv run scripts/gemini_image_gen.py generate \
  --prompt "Da Vinci style anatomical sketch of a Monarch butterfly on textured parchment" \
  --model gemini-3-pro-image-preview \
  --resolution 4K \
  --aspect-ratio 1:1
```

Search-grounded generation:
```
uv run scripts/gemini_image_gen.py generate \
  --prompt "Visualize the current weather forecast for San Francisco as a modern chart" \
  --model gemini-3-pro-image-preview \
  --google-search \
  --aspect-ratio 16:9
```

Style transfer with reference image:
```
uv run scripts/gemini_image_gen.py edit \
  --prompt "Apply Image 1's visual style to a cityscape" \
  --image style_reference.png \
  --out output/styled_city.png
```

## See also
- API parameter quick reference: `references/gemini-api.md`
- Prompt examples: `references/sample-prompts.md`
- Prompting best practices: `references/prompting.md`
- Vertex AI setup: `references/vertex-setup.md`
