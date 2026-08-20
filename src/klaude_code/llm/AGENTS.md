# LLM Multimodal Input Notes

These notes summarize the local policy for multimodal image data. The important distinction is
that token context and request byte size are separate limits: base64 images can overflow the HTTP
payload while token usage still looks healthy.

## Design Principle

Keep durable history stable and lightweight, and treat media hydration as a provider-boundary
concern. Do not repeatedly rewrite old prompt prefixes with changing inline base64 decisions unless
there is no better fallback.

## Image History Storage

Do not persist inline base64 image payloads in conversation history. History entries should store image references, preferably `ImageFilePart` objects pointing at session-scoped snapshots under `ProjectPaths.images_dir(session_id)`. Session snapshots should already be request-ready and marked frozen, so provider input conversion can hydrate them into base64 request blocks without recompressing old prompt prefixes differently on later turns.

This keeps `events.jsonl` small, avoids replaying large blobs through every step, and preserves prompt-cache stability better than dynamically rewriting old history.

## Request-Time Hydration

Provider adapters convert `ImageFilePart` to provider-specific image blocks through helpers in `llm/image.py` and `llm/input_common.py`. Keep this conversion deterministic for the same file bytes. Before base64 encoding, use the shared Pillow-based optimization and request budget rather than adding provider-local image rewriting. When the media budget is exceeded, `apply_inline_image_budget()` preserves the most recent contiguous media suffix and inserts omitted-image text for dropped or missing images.

## Non-Vision Models

Models with `supports_vision: false` in config (e.g. glm, deepseek) must never receive image blocks. `apply_config_defaults()` in `llm/input_common.py` strips image parts from `param.input` via `strip_images_for_text_only_model()` before any provider conversion runs: user/developer image parts become text placeholders, tool-result image parts are dropped with a placeholder appended to `output_text`. The placeholder names the image path and points the model at the `LookAt` tool, which routes the image through a vision-capable fast model. Because the strip happens at request time, history images and mid-session model switches are covered automatically; stripped copies never mutate shared history objects.

## Compaction And Summaries

The fallback serializer in `agent/compaction/compaction.py` records image file paths or URLs in an
`image: ...` text line rather than carrying binary payloads. The cache-sharing fork compaction path
uses the actual LLM-facing prefix, so images on that path still rely on the normal provider request
budget and omitted-image fallback.

## Cache And Payload Limits

Image handling must consider both token context and raw HTTP request size. A model can have ample token context left while base64 media pushes the request body over provider byte limits. Do not rely only on token-based compaction to manage multimodal sessions.
