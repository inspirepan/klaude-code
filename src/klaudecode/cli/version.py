from ..tui import ColorStyle, Text, console


def version_command():
    """Show version information"""
    from importlib.metadata import version

    try:
        pkg_version = version('klaude-code')
        console.print(Text(f'klaude-code {pkg_version}', style=ColorStyle.SUCCESS))
    except Exception:
        console.print(Text('klaude-code (development)', style=ColorStyle.SUCCESS))
