"""
Oh-My-Logo Python CLI
Generates single-color characters without gradient effects
"""

import argparse
import sys
from typing import List

# Unicode box drawing characters for letters
# fmt: off
BOX_LETTERS = {
    'A': [
        " ██████╗",
        "██╔══██╗",
        "███████║",
        "██╔══██║",
        "██║  ██║",
        "╚═╝  ╚═╝"
    ],
    'B': [
        "██████╗ ",
        "██╔══██╗",
        "██████╔╝",
        "██╔══██╗",
        "██████╔╝",
        "╚═════╝ "
    ],
    'C': [
        " ██████╗",
        "██╔════╝",
        "██║     ",
        "██║     ",
        "╚██████╗",
        " ╚═════╝"
    ],
    'D': [
        "██████╗ ",
        "██╔══██╗",
        "██║  ██║",
        "██║  ██║",
        "██████╔╝",
        "╚═════╝ "
    ],
    'E': [
        "███████╗",
        "██╔════╝",
        "█████╗  ",
        "██╔══╝  ",
        "███████╗",
        "╚══════╝"
    ],
    'F': [
        "███████╗",
        "██╔════╝",
        "█████╗  ",
        "██╔══╝  ",
        "██║     ",
        "╚═╝     "
    ],
    'G': [
        " ██████╗ ",
        "██╔════╝ ",
        "██║ ███╗ ",
        "██║   ██╗",
        "╚██████╔╝",
        " ╚═════╝ "
    ],
    'H': [
        "██╗  ██╗",
        "██║  ██║",
        "███████║",
        "██╔══██║",
        "██║  ██║",
        "╚═╝  ╚═╝"
    ],
    'I': [
        "██╗ ",
        "██║ ",
        "██║ ",
        "██║ ",
        "██║ ",
        "╚═╝ "
    ],
    'J': [
        "     ██╗",
        "     ██║",
        "     ██║",
        "██   ██║",
        "╚█████╔╝",
        " ╚════╝ "
    ],
    'K': [
        "██╗  ██╗",
        "██║ ██╔╝",
        "█████╔╝ ",
        "██╔═██╗ ",
        "██║  ██╗",
        "╚═╝  ╚═╝"
    ],
    'L': [
        "██╗     ",
        "██║     ",
        "██║     ",
        "██║     ",
        "███████╗",
        "╚══════╝"
    ],
    'M': [
        "███╗   ███╗",
        "████╗ ████║",
        "██╔████╔██║",
        "██║╚██╔╝██║",
        "██║ ╚═╝ ██║",
        "╚═╝     ╚═╝"
    ],
    'N': [
        "███╗   ██╗",
        "████╗  ██║",
        "██╔██╗ ██║",
        "██║╚██╗██║",
        "██║ ╚████║",
        "╚═╝  ╚═══╝"
    ],
    'O': [
        " ██████╗ ",
        "██╔═══██╗",
        "██║   ██║",
        "██║   ██║",
        "╚██████╔╝",
        " ╚═════╝ "
    ],
    'P': [
        "██████╗ ",
        "██╔══██╗",
        "██████╔╝",
        "██╔═══╝ ",
        "██║     ",
        "╚═╝     "
    ],
    'Q': [
        " ██████╗ ",
        "██╔═══██╗",
        "██║   ██║",
        "██║▄▄ ██║",
        "╚██████╔╝",
        " ╚══▀▀═╝ "
    ],
    'R': [
        "██████╗ ",
        "██╔══██╗",
        "██████╔╝",
        "██╔══██╗",
        "██║  ██║",
        "╚═╝  ╚═╝"
    ],
    'S': [
        "███████╗",
        "██╔════╝",
        "███████╗",
        "╚════██║",
        "███████║",
        "╚══════╝"
    ],
    'T': [
        "████████╗",
        "╚══██╔══╝",
        "   ██║   ",
        "   ██║   ",
        "   ██║   ",
        "   ╚═╝   "
    ],
    'U': [
        "██╗   ██╗",
        "██║   ██║",
        "██║   ██║",
        "██║   ██║",
        "╚██████╔╝",
        " ╚═════╝ "
    ],
    'V': [
        "██╗   ██╗",
        "██║   ██║",
        "██║   ██║",
        "╚██╗ ██╔╝",
        " ╚████╔╝ ",
        "  ╚═══╝  "
    ],
    'W': [
        "██╗    ██╗",
        "██║    ██║",
        "██║ █╗ ██║",
        "██║███╗██║",
        "╚███╔███╔╝",
        " ╚══╝╚══╝ "
    ],
    'X': [
        "██╗  ██╗",
        "╚██╗██╔╝",
        " ╚███╔╝ ",
        " ██╔██╗ ",
        "██╔╝ ██╗",
        "╚═╝  ╚═╝"
    ],
    'Y': [
        "██╗   ██╗",
        "╚██╗ ██╔╝",
        " ╚████╔╝ ",
        "  ╚██╔╝  ",
        "   ██║   ",
        "   ╚═╝   "
    ],
    'Z': [
        "███████╗",
        "╚══███╔╝",
        "  ███╔╝ ",
        " ███╔╝  ",
        "███████╗",
        "╚══════╝"
    ],
    ' ': [
        " ",
        " ",
        " ",
        " ",
        " ",
        " "
    ],
    '-': [
        "       ",
        "       ",
        "███████",
        "╚══════",
        "       ",
        "       "
    ]
}
# fmt: on

# Predefined colors
COLORS = {
    'red': '\033[31m',
    'green': '\033[32m',
    'yellow': '\033[33m',
    'blue': '\033[34m',
    'magenta': '\033[35m',
    'cyan': '\033[36m',
    'white': '\033[37m',
    'bright_red': '\033[91m',
    'bright_green': '\033[92m',
    'bright_yellow': '\033[93m',
    'bright_blue': '\033[94m',
    'bright_magenta': '\033[95m',
    'bright_cyan': '\033[96m',
    'bright_white': '\033[97m',
}


def hex_to_ansi(hex_color: str) -> str:
    """Convert hex color to ANSI color code"""
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f'\033[38;2;{r};{g};{b}m'


def generate_box_drawing_text(text: str) -> List[str]:
    """Generate box drawing ASCII art"""
    text = text.upper()
    lines = [''] * 6

    for char in text:
        if char in BOX_LETTERS:
            char_lines = BOX_LETTERS[char]
            for i in range(6):
                lines[i] += char_lines[i]
        else:
            # Undefined characters are displayed as question marks
            for i in range(6):
                lines[i] += '  ?  '

    return lines


def apply_color(lines: List[str], color_code: str) -> str:
    """Apply single color to all lines"""
    colored_lines = []
    reset_code = '\033[0m'

    for line in lines:
        if not line.strip():
            colored_lines.append(line)
            continue

        # Apply color to the entire line
        colored_lines.append(f'{color_code}{line}{reset_code}')

    return '\n'.join(colored_lines)


def main():
    parser = argparse.ArgumentParser(
        description='Generate single-color ASCII art logos',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "HELLO" red
  %(prog)s "WORLD" blue
  %(prog)s "CODE" "#ff5e62"
  %(prog)s --list-colors
        """,
    )

    parser.add_argument('text', nargs='?', default='', help='Text to render')
    parser.add_argument('color', nargs='?', default='white', help='Color name or hex code (default: white)')
    parser.add_argument('--list-colors', action='store_true', help='List all available color names')

    args = parser.parse_args()

    if args.list_colors or (not args.text and not args.list_colors):
        print('\nAvailable color names:')
        print('=' * 30)
        for name in COLORS.keys():
            color_code = COLORS[name]
            print(f'  {color_code}{name:<15}\033[0m')
        print('\nYou can also use hex colors like: #ff5e62')
        print()
        return

    # Parse color
    if args.color.startswith('#'):
        # Hex color
        try:
            color_code = hex_to_ansi(args.color)
        except Exception as e:
            print(e)
            print(f"Error: Invalid hex color '{args.color}'")
            print('Hex colors should be in format: #RRGGBB')
            sys.exit(1)
    elif args.color.lower() in COLORS:
        # Predefined color name
        color_code = COLORS[args.color.lower()]
    else:
        print(f"Error: Unknown color '{args.color}'")
        print(f'Available colors: {", ".join(COLORS.keys())}')
        print('Or use hex format like: #ff5e62')
        sys.exit(1)

    # Generate and output logo
    lines = generate_box_drawing_text(args.text)
    colored_output = apply_color(lines, color_code)
    print('\n' + colored_output + '\n')


if __name__ == '__main__':
    main()
