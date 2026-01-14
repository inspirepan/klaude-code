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
