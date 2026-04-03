from __future__ import annotations

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

SIMPLIFIER_SUMMARY = (
    "Code simplification agent that refines recently changed code for clarity and consistency.\n"
    "- Use for: Cleaning up code after implementation -- reducing nesting, eliminating redundancy,\n"
    "  improving naming, and aligning with project conventions\n"
    "- Don't use for: Bug fixing, feature changes, architecture decisions, or style-only formatting\n"
    "- The prompt must include:\n"
    "  1. Diff command: a shell command to view the recent changes (e.g. `git diff`, `git diff HEAD~1`)\n"
    "  2. Scope (optional): specific files or areas to focus on\n"
    "  3. Constraints (optional): project conventions or patterns to preserve\n"
    "- The agent reads project conventions autonomously, applies targeted simplifications,\n"
    "  and reports what was changed and why.\n"
    "(Tools: Bash, Read, Edit)"
)

register_sub_agent(
    SubAgentProfile(
        name="code-simplifier",
        prompt_file="prompts/prompt-sub-agent-simplifier.md",
        tool_set=(tools.BASH, tools.READ, tools.EDIT),
        invoker_summary=SIMPLIFIER_SUMMARY,
        active_form="Simplifying",
    )
)
