EXIT_PLAN_MODE_TOOL_PLAN_ARG_DESC = """The plan you came up with, that you want to run by the user for approval. Supports markdown. The plan should be pretty concise.
"""

EXIT_PLAN_MODE_TOOL_DESC = """Use this tool when you are in plan mode and have finished presenting your plan and are ready to code. This will prompt the user to exit plan mode.
IMPORTANT: Only use this tool when the task requires planning the implementation steps of a task that requires writing code. For research tasks where you're gathering information, searching files, reading files or in general trying to understand the codebase - do NOT use this tool.

Eg.

Initial task: "Search for and understand the implementation of vim mode in the codebase" - Do not use the exit plan mode tool because you are not planning the implementation steps of a task.
Initial task: "Help me implement yank mode for vim" - Use the exit plan mode tool after you have finished planning the implementation steps of the task.
"""

PLAN_MODE_REMINDER = """<system-reminder>Plan mode is active. The user indicated that they do not want you to execute yet -- you MUST NOT make any edits, run any non-readonly tools (including changing configs or making commits), or otherwise make any changes to the system. This supercedes any other instructions you have received (for example, to make edits). Instead, you should:
1. Answer the user's query
2. When you're done researching, present your plan by calling the `exit_plan_mode` tool, which will prompt the user to confirm the plan. Do NOT make any file changes or run any tools that modify the system state in any way until the user has confirmed the plan.</system-reminder>"""


APPROVE_MSG = """User has approved your plan. You can now start coding. Start with updating your todo list if applicable"""
APPROVE_HINT = """User approved Claude's plan"""


REJECT_MSG = """The user doesn't want to proceed with this tool use. The tool use was rejected (eg. if it was a file edit, the new_string was NOT written to the file). STOP what you are doing and wait for the user to tell you how to proceed."""
REJECT_HINT = """User rejected Claude's plan"""
