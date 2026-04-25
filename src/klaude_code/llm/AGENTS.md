# LLM Multimodal Input Notes

These notes summarize the local policy and the Claude Code reference design for multimodal image data. The important distinction is that token context and request byte size are separate limits: base64 images can overflow the HTTP payload while token usage still looks healthy.

## Claude Code Reference

Claude Code avoids making inline image base64 part of durable prompt history. In the reference implementation, prompt history filters image pasted content because images are stored separately in an image cache (`src/history.ts`). Images are compressed before API use (`src/utils/imageResizer.ts`) with several fallbacks: dimension downscaling, PNG compression, JPEG quality reduction, and final aggressive resize. API-facing constants live in `src/constants/apiLimits.ts`, including 5 MB max base64 image size and 2000 px image dimensions.

Claude Code still has request-time fallbacks. `stripExcessMediaItems()` in `src/services/api/claude.ts` drops the oldest media items when the API media count limit would be exceeded, preserving recent media. Compaction uses `stripImagesFromMessages()` in `src/services/compact/compact.ts` to replace image/document blocks with `[image]` / `[document]` text markers before summarization, so compaction itself does not resend historical binary payloads.

The cache lesson from Claude Code is: keep durable history stable and lightweight, and treat media hydration as a provider-boundary concern. Do not repeatedly rewrite old prompt prefixes with changing inline base64 decisions unless there is no better fallback.

## Image History Storage

Do not persist inline base64 image payloads in conversation history. History entries should store image references, preferably `ImageFilePart` objects pointing at session-scoped snapshots under `ProjectPaths.images_dir(session_id)`. Session snapshots should already be request-ready and marked frozen, so provider input conversion can hydrate them into base64 request blocks without recompressing old prompt prefixes differently on later turns.

This keeps `events.jsonl` small, avoids replaying large blobs through every turn, and preserves prompt-cache stability better than dynamically rewriting old history.

## Request-Time Hydration

Provider adapters may convert `ImageFilePart` to provider-specific image blocks using `image_file_to_data_url()`. Keep this conversion deterministic for the same file bytes. Before base64 encoding, use Pillow-based optimization to keep single-image payloads under provider limits: downscale large dimensions, optimize PNG/JPEG/WebP encodings, and fall back to JPEG quality steps when lossless output remains too large. If request payload limits are still approached, trim old media only as a fallback in the provider input layer; prefer preserving the most recent contiguous media suffix.

## Compaction And Summaries

Compaction or summarization requests should not resend full historical images unless the summary task explicitly needs visual content. Replace images/documents with short text markers such as `[image]` or an omitted-image note so the model knows media existed without carrying the binary payload.

## Cache And Payload Limits

Image handling must consider both token context and raw HTTP request size. A model can have ample token context left while base64 media pushes the request body over provider byte limits. Do not rely only on token-based compaction to manage multimodal sessions.
