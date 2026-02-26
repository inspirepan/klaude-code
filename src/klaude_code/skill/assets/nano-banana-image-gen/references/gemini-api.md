# Gemini Image API quick reference

## Models
| Model | ID | Best for |
|---|---|---|
| Nano Banana / Nano Banana 2 (Flash) | `gemini-3.1-flash-image-preview` | Speed-quality balance, Thinking, Search grounding, 512px mode; <=3 input images |
| Nano Banana Pro | `gemini-3-pro-image-preview` | Professional assets, 4K, text rendering, Search grounding, Thinking; up to 14 input images |

## Authentication
The CLI auto-detects credentials (checked in order):
1. **API key**: `GEMINI_API_KEY` -> `genai.Client(api_key=key)`
2. **Vertex AI**: `GOOGLE_APPLICATION_CREDENTIALS` + `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION` -> `genai.Client(vertexai=True, credentials=..., project=..., location=...)`

See `references/vertex-setup.md` for Vertex AI setup details.

## API call pattern (Python SDK)
```python
from google import genai
from google.genai import types

# Option 1: API key
client = genai.Client(api_key="your-key")

# Option 2: Vertex AI
from google.auth import load_credentials_from_file
credentials, _ = load_credentials_from_file("sa-key.json",
    scopes=["https://www.googleapis.com/auth/cloud-platform"])
client = genai.Client(vertexai=True, credentials=credentials,
    project="my-project", location="us-central1")

# Generate (same for both):
response = client.models.generate_content(
    model="gemini-3.1-flash-image-preview",
    contents=[prompt],  # or [prompt, image1, image2, ...]
    config=types.GenerateContentConfig(
        response_modalities=['TEXT', 'IMAGE'],
        image_config=types.ImageConfig(
            aspect_ratio="16:9",
            image_size="2K",
        ),
        tools=[{"google_search": {}}],  # optional
    )
)
```

## Response handling
```python
for part in response.parts:
    if part.text is not None:
        print(part.text)
    elif part.inline_data is not None:
        image = part.as_image()
        image.save("output.png")
```

## Configuration parameters

### `response_modalities`
- `['TEXT', 'IMAGE']` (default): model may return text and/or images
- `['Image']`: image-only output

### `image_config`
- `aspect_ratio`: `1:1` (default), `1:4`, `1:8`, `2:3`, `3:2`, `3:4`, `4:1`, `4:3`, `4:5`, `5:4`, `8:1`, `9:16`, `16:9`, `21:9`
  - `1:4`, `1:8`, `4:1`, `8:1` are Nano Banana 2 only.
- `image_size`:
  - Nano Banana 2: `512px`, `1K`, `2K`, `4K`
  - Pro: `1K`, `2K`, `4K`

### `tools`
- `[{"google_search": {}}]`: enables Google Search grounding (supported by Nano Banana 2 + Pro)

## Input constraints
- Nano Banana 2: best with <=3 input images
- Pro model: up to 14 input images total (up to 5 humans high-fidelity, up to 6 objects high-fidelity)
- No audio/video input supported for image generation

## Nano Banana 2 specifics
- Supports Thinking and Thinking Levels via `thinking_config`.
- Supports low-latency `512px` image size.
- Supports image-grounding search mode (`google_search.search_types.image_search`) in addition to web text grounding.

## Output
- Response parts contain `text` and/or `inline_data` (image bytes)
- `part.as_image()` returns a PIL Image object directly
- `part.inline_data.data` contains raw bytes (not base64)
- All generated images include SynthID watermark

## Pro model specifics
- Thinking mode: enabled by default, cannot be disabled. Generates up to 2 interim "thought images" (not charged).
- Thought signatures: automatically handled by SDK chat feature. For manual multi-turn, pass `thought_signature` back.
- Google Search grounding: image-based search results are NOT passed to the generation model.
- Text rendering: significantly better than Flash; recommended for infographics, logos, marketing assets.

## Supported languages
EN, ar-EG, de-DE, es-MX, fr-FR, hi-IN, id-ID, it-IT, ja-JP, ko-KR, pt-BR, ru-RU, ua-UA, vi-VN, zh-CN

## Limitations
- Output image count is not strictly guaranteed to match user request.
- Pro model Thinking adds latency but improves complex prompt adherence.
- `response_modalities=['Image']` may not work reliably with Search grounding.
- Use rights compliance required for uploaded images (Prohibited Use Policy).
