from __future__ import annotations

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

REVIEW_SUMMARY = (
    "Code review agent that identifies real bugs in proposed changes.\n"
    "- Use for: Complex, multi-file changes with non-trivial logic that could harbor subtle bugs\n"
    "- Don't use for: Small/simple changes (single-file edits, config tweaks, renames, typo fixes, "
    "straightforward bug fixes), style/formatting checks, or general code exploration\n"
    "- IMPORTANT: Only invoke review ONCE per task. After fixing issues found by a review, do NOT\n"
    "  launch another review to verify the fixes -- apply your own judgement instead. A second\n"
    "  review is only warranted if the user explicitly asks for one.\n"
    "- The prompt must include:\n"
    "  1. Background: what the user asked for, the intent behind the changes, key decisions and tradeoffs made\n"
    "  2. Diff command: a shell command to view the changes (e.g. `git diff`, `git diff --cached`)\n"
    "  3. Key files: list the most important files changed and any related files for context\n"
    "  4. Focus (optional): specific concerns or areas to pay extra attention to\n"
    "- For follow-up reviews (after fixing issues from a prior review): include the previous\n"
    "  findings in the prompt and scope the diff command to only the fix commits, so the agent\n"
    "  can verify fixes incrementally instead of re-reviewing the entire changeset.\n"
    "- The agent reads surrounding context autonomously and returns structured findings\n"
    "  with priority levels.\n"
    "(Tools: Bash, Read)"
)

register_sub_agent(
    SubAgentProfile(
        name="review",
        prompt_file="prompts/prompt-sub-agent-review.md",
        tool_set=(tools.BASH, tools.READ),
        invoker_summary=REVIEW_SUMMARY,
        active_form="Reviewing",
    )
)
