---
name: "nano-banana-image-gen"
description: "Use when the user asks to generate or edit images with Nano Banana / Nano Banana Pro (users often call these models 'banana'). Nano Banana maps to `gemini-2.5-flash-image`; Nano Banana Pro maps to `gemini-3-pro-image`."
---

# Nano Banana Image Generation Skill

Generate or edit images using Google's Gemini native image generation. Naming note: **Nano Banana** is the marketing name for `gemini-2.5-flash-image`, and **Nano Banana Pro** maps to `gemini-3-pro-image` (currently exposed in this CLI as `gemini-3-pro-image-preview`).

## When to use
- Generate a new image (concept art, product shot, cover, hero, sticker, icon)
- Edit an existing image (style change, object removal, background replacement, text localization)
- Multi-image composition (combine up to 14 reference images)
- Search-grounded generation (real-time data like weather, events, charts)

## Model selection
- `gemini-2.5-flash-image` (Nano Banana, default): fast, low-latency, high-volume. Best with <=3 input images.
- `gemini-3-pro-image-preview` (Nano Banana Pro / `gemini-3-pro-image`): professional asset production, advanced text rendering, Thinking mode, up to 4K, Google Search grounding. Supports up to 14 input images (5 humans high-fidelity, 6 objects high-fidelity).

Use Pro when the user needs: 4K resolution, accurate text rendering, Search grounding, complex multi-image composition, or explicitly requests "pro" / "high quality".

## Decision tree
- If the user provides input image(s) or says "edit/retouch/change/modify/localize" -> **edit**
- If the user needs Search-grounded imagery (current weather, live data) -> **generate with --google-search**
- Else -> **generate**

## Workflow
1. Decide intent: generate vs edit (see decision tree).
2. Collect inputs: prompt, input images (if any), constraints, text to render (verbatim).
3. Choose model: Flash (default) or Pro (see model selection above).
4. Augment prompt into a structured spec (see prompt augmentation below); do not invent new creative requirements.
5. Run the bundled CLI (`scripts/gemini_image_gen.py`). See `references/cli.md` for commands and flags.
6. Inspect outputs and validate: subject, style, composition, text accuracy.
7. Iterate: make a single targeted change, re-run, re-check.
8. Save final outputs and note the final prompt + flags used.

## Output conventions
- Write final artifacts under `output/imagegen/` when working in this repo.
- Use `--out` to control output path; keep filenames stable and descriptive.

## Dependencies
```
uv run --with google-genai --with google-auth --with pillow scripts/gemini_image_gen.py generate --prompt "test" --dry-run
```

## Authentication
The CLI auto-detects credentials in this order:
1. **API key**: `GEMINI_API_KEY` -- simplest option, get one at https://aistudio.google.com/apikey
2. **Vertex AI**: `GOOGLE_APPLICATION_CREDENTIALS` + `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION` -- for enterprise/GCP users with service account credentials.

If no credentials are found, the CLI gives setup instructions for both options.
Never ask the user to paste keys in chat. Ask them to set env vars locally.

For Vertex AI setup details: `references/vertex-setup.md`.

## Defaults & rules
- Model: `gemini-2.5-flash-image` unless user asks for Pro or needs Pro features.
- Aspect ratio: `1:1` (default). Supported: `1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9`.
- Resolution: `1K` (default). Pro model supports `1K, 2K, 4K`. Must use uppercase `K`.
- Response modalities: `TEXT,IMAGE` by default. Use `--image-only` for image-only output.
- Output format: PNG (default).
- Prefer the bundled CLI over writing new scripts.
- Never modify `scripts/gemini_image_gen.py`. Ask the user if something is missing.

## Prompt augmentation
Reformat user prompts into a structured spec. Only make implicit details explicit; do not invent new requirements.

Template (include only relevant lines):
```
Use case: <taxonomy slug>
Primary request: <user's main prompt>
Scene/background: <environment>
Subject: <main subject>
Style/medium: <photo/illustration/3D/etc>
Composition/framing: <wide/close/top-down; placement>
Lighting/mood: <lighting + mood>
Color palette: <palette notes>
Text (verbatim): "<exact text>"
Constraints: <must keep/must avoid>
Avoid: <negative constraints>
```

## Use-case taxonomy
Generate:
- photorealistic-scene -- candid/editorial photos with real texture and natural lighting
- product-mockup -- product/packaging shots, catalog imagery
- ui-mockup -- app/web interface mockups
- infographic-diagram -- diagrams/infographics with structured layout and text
- logo-brand -- logo/mark exploration, minimal flat design
- illustration-sticker -- icons, stickers, kawaii art, children's book art
- stylized-concept -- style-driven concept art, 3D renders
- minimalist-negative-space -- backgrounds for websites/presentations with text overlay space
- search-grounded -- real-time data visualization (weather, charts, events)

Edit:
- style-transfer -- apply reference style to new subject
- object-edit -- remove/replace specific elements
- text-localization -- translate/replace in-image text
- multi-image-composition -- combine multiple reference images
- sketch-to-render -- drawing/line art to photoreal render

## Prompting best practices (short list)
- Describe the scene narratively; do not just list keywords.
- Use photography language for photorealism (lens, lighting, framing).
- For text in images: quote exact text, specify font style descriptively, use Pro model.
- For Pro model: let Thinking work; complex prompts get better results.
- For Search grounding: describe what real-time data to visualize.
- For edits, repeat invariants ("change only X; keep Y unchanged").
- Iterate with single-change follow-ups.

More principles: `references/prompting.md`. Copy/paste specs: `references/sample-prompts.md`.

## CLI + environment notes
- CLI commands + examples: `references/cli.md`
- API parameter quick reference: `references/gemini-api.md`
- Vertex AI setup guide: `references/vertex-setup.md`

## Reference map
- **`references/cli.md`**: how to run generation/edits via `scripts/gemini_image_gen.py` (commands, flags, recipes).
- **`references/gemini-api.md`**: API-level parameters, models, authentication modes, constraints.
- **`references/prompting.md`**: prompting principles, strategies, and templates from Google's official guide.
- **`references/sample-prompts.md`**: copy/paste prompt recipes for each use-case taxonomy slug.
- **`references/vertex-setup.md`**: how to configure Vertex AI credentials (service account, env vars, IAM roles).
