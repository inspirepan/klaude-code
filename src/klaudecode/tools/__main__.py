"""Main module for running tools package"""

import json

try:
    from rich.console import Console
    from rich.syntax import Syntax

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def get_all_tools():
    from . import BashTool, EditTool, ExitPlanModeTool, GlobTool, GrepTool, LsTool, MultiEditTool, ReadTool, TodoReadTool, TodoWriteTool, WriteTool
    from .task import TaskTool

    return [
        BashTool,
        TodoReadTool,
        TodoWriteTool,
        ExitPlanModeTool,
        ReadTool,
        EditTool,
        MultiEditTool,
        WriteTool,
        LsTool,
        GrepTool,
        GlobTool,
        TaskTool,
    ]


def get_all_tools_openai_schema():
    """Get OpenAI schema for all tools"""
    return {tool.get_name(): tool.openai_schema() for tool in get_all_tools()}


def main():
    """Main function to print all tools schema"""
    # Get all tool schemas
    all_schemas = get_all_tools_openai_schema()

    # Convert to formatted JSON
    formatted_json = json.dumps(all_schemas, indent=2, ensure_ascii=False)

    if RICH_AVAILABLE:
        # Create Rich console
        console = Console()

        # Use Rich syntax highlighting
        syntax = Syntax(formatted_json, 'json', theme='github-dark', line_numbers=True, word_wrap=True)

        # Print title
        console.print('\n[bold cyan]All Tools OpenAI Schema[/bold cyan]\n')

        # Print highlighted JSON
        console.print(syntax)

        # Print tool statistics
        console.print(f'\n[green]Total: {len(all_schemas)} tools[/green]\n')
    else:
        # Use regular print if Rich is not available
        print('\nAll Tools OpenAI Schema\n')
        print(formatted_json)
        print(f'\nTotal: {len(all_schemas)} tools\n')


if __name__ == '__main__':
    main()
