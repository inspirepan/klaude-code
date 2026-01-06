Fetch content from a URL and return it in a readable format.

The tool automatically processes the response based on Content-Type:
- HTML pages are converted to Markdown for easier reading
- JSON responses are formatted with indentation
- Markdown and other text content is returned as-is

Content is always saved to a local file. The file path is shown at the start of the output in `[Web content saved to ...]` format. For large content that gets truncated, you can read the saved file directly.
