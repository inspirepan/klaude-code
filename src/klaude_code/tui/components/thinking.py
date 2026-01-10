import re

# UI markers
THINKING_MESSAGE_MARK = "∴"


def normalize_thinking_content(content: str) -> str:
    """Normalize thinking content for display."""
    text = content.rstrip()

    # Weird case of Gemini 3
    text = text.replace("\\n\\n\n\n", "")

    # Fix OpenRouter OpenAI reasoning formatting where segments like
    # "text**Title**\n\n" lose the blank line between segments.
    # We want: "text\n**Title**\n" so that each bold title starts on
    # its own line and uses a single trailing newline.
    text = re.sub(r"([^\n])(\*\*[^*]+?\*\*)\n\n", r"\1  \n\n\2  \n", text)

    # Remove extra newlines between back-to-back bold titles, eg
    # "**Title1****Title2**" -> "**Title1**\n\n**Title2**".
    text = text.replace("****", "**\n\n**")

    # Compact double-newline after bold so the body text follows
    # directly after the title line, using a markdown line break.
    text = text.replace("**\n\n", "**  \n")

    return text


def extract_last_bold_header(text: str) -> str | None:
    """Extract the latest complete bold header ("**…**") from text.

    We treat a bold segment as a "header" only if it appears at the beginning
    of a line (ignoring leading whitespace). This avoids picking up incidental
    emphasis inside paragraphs.

    Returns None if no complete bold segment is available yet.
    """

    last: str | None = None
    i = 0
    while True:
        start = text.find("**", i)
        if start < 0:
            break

        line_start = text.rfind("\n", 0, start) + 1
        if text[line_start:start].strip():
            i = start + 2
            continue

        end = text.find("**", start + 2)
        if end < 0:
            break

        inner = " ".join(text[start + 2 : end].split())
        if inner and "\n" not in inner:
            last = inner

        i = end + 2

    return last
