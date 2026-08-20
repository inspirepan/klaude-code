Inspect a local image file by asking a vision model about it. Returns a text answer.

You cannot view images directly; this tool is your way to "see" an image (screenshot, diagram, photo, UI mockup, chart). A separate vision-capable model reads the pixels and answers your question in text.

Usage:
- The file_path parameter must be an absolute path to a local image file (png, jpg, jpeg, gif, webp)
- Whenever a message or tool result contains a placeholder like "[image not sent: ... path=...]", pass that path to this tool to view the image
- Ask a specific question; the answer quality depends on it. For a first look, ask for a full description
- The optional region parameter [x1, y1, x2, y2] crops the original image in pixel coordinates before sending, so the cropped area keeps full resolution. Load the full image first, then call again with a region to zoom into details (small text, UI elements, fine print)
- For a remote image, download it first (e.g. Bash curl) and pass the local path
- Each call costs one auxiliary model request; batch related questions into one call when possible
