from typing import Tuple


def count_occurrences(content: str, search_string: str) -> int:
    """Count occurrences of search string in content.

    Args:
        content: Text content to search
        search_string: String to count

    Returns:
        Number of occurrences
    """
    return content.count(search_string)


def replace_string_in_content(content: str, old_string: str, new_string: str, replace_all: bool = False) -> Tuple[str, int]:
    """Replace occurrences of old_string with new_string in content.

    Args:
        content: Text content to modify
        old_string: String to replace
        new_string: Replacement string
        replace_all: Whether to replace all occurrences or just first

    Returns:
        Tuple of (modified_content, replacement_count)
    """
    if replace_all:
        new_content = content.replace(old_string, new_string)
        count = content.count(old_string)
    else:
        new_content = content.replace(old_string, new_string, 1)
        count = 1 if old_string in content else 0

    return new_content, count


def try_colorblind_compatible_match(content: str, old_string: str) -> Tuple[bool, str]:
    """
    Handle model "colorblindness" issue where full tag names might be
    misinterpreted as shortened versions.

    Common patterns:
    - <result> and </result> misinterpreted as <r> and </r>
    - <output> and </output> misinterpreted as <o> and </o>
    - <name> and </name> misinterpreted as <n> and </n>
    - etc.

    This function attempts to find the intended string by expanding
    shortened tags to their full versions.

    Args:
        content: The file content to search in
        old_string: The original string that was not found

    Returns:
        Tuple of (found, corrected_string) where:
        - found: True if a compatible match was found
        - corrected_string: The corrected string that was actually found in content
    """

    # Define mapping of shortened tags to their full versions
    tag_mappings = {
        '<r>': '<result>',
        '</r>': '</result>',
        '<o>': '<output>',
        '</o>': '</output>',
        '<n>': '<name>',
        '</n>': '</name>',
        '<t>': '<type>',
        '</t>': '</type>',
        '<i>': '<input>',
        '</i>': '</input>',
        '<d>': '<description>',
        '</d>': '</description>',
        '<c>': '<content>',
        '</c>': '</content>',
        '<f>': '<function>',
        '</f>': '</function>',
        '<m>': '<method>',
        '</m>': '</method>',
        '<p>': '<parameter>',
        '</p>': '</parameter>',
        '<v>': '<value>',
        '</v>': '</value>',
        '<s>': '<string>',
        '</s>': '</string>',
    }

    # Check if old_string contains any shortened tags
    has_shortened_tags = any(short_tag in old_string for short_tag in tag_mappings.keys())

    if not has_shortened_tags:
        return False, old_string

    # Try expanding all shortened tags to their full versions
    corrected_string = old_string
    for short_tag, full_tag in tag_mappings.items():
        corrected_string = corrected_string.replace(short_tag, full_tag)

    # Check if the corrected string exists in content
    if corrected_string in content:
        return True, corrected_string

    return False, old_string
