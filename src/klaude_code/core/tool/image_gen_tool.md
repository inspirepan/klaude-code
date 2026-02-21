Generate one or more images from a text prompt.

This tool invokes an Image Gen model to generate images. The generated image paths are automatically returned in the response.

Inputs:
- `prompt`: The main instruction describing the desired image.
- `image_paths` (optional): Local image file paths to use as references for editing or style guidance.
- `generation` (optional): Per-call image generation settings (aspect ratio / size).

Notes:
- Provide a short textual description of the generated image(s).
- Do NOT include base64 image data in text output.
- When providing multiple input images, describe each image's characteristics and purpose in the prompt, not just "image 1, image 2".

Multi-turn image editing:
- Use `resume` to continue editing a previously generated image. The agent preserves its full context including the generated image, so you don't need to pass `image_paths` again.