from __future__ import annotations

from typing import Any

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

ORACLE_DESCRIPTION = """\
Consult the Oracle - an AI advisor powered by OpenAI's premium reasoning model that can plan, review, and provide expert guidance.

The Oracle has access to the following tools: Read, Bash.

The Oracle acts as your senior engineering advisor and can help with:

WHEN TO USE THE ORACLE:
- Code reviews and architecture feedback
- Finding a bug in multiple files
- Planning complex implementations or refactoring
- Analyzing code quality and suggesting improvements
- Answering complex technical questions that require deep reasoning

WHEN NOT TO USE THE ORACLE:
- Simple file reading or searching tasks (use Read or Grep directly)
- Codebase searches (use Task)
- Basic code modifications and when you need to execute code changes (do it yourself or use Task)

USAGE GUIDELINES:
1. Be specific about what you want the Oracle to review, plan, or debug
2. Provide relevant context about what you're trying to achieve. If you know that any files are involved, list them and they will be attached.


EXAMPLES:
- "Review the authentication system architecture and suggest improvements"
- "Plan the implementation of real-time collaboration features"
- "Analyze the performance bottlenecks in the data processing pipeline"
- "Review this API design and suggest better patterns"\
"""

ORACLE_PARAMETERS = {
    "properties": {
        "context": {
            "description": "Optional context about the current situation, what you've tried, or background information that would help the Oracle provide better guidance.",
            "type": "string",
        },
        "files": {
            "description": "Optional list of specific file paths (text files, images) that the Oracle should examine as part of its analysis. These files will be attached to the Oracle input.",
            "items": {"type": "string"},
            "type": "array",
        },
        "task": {
            "description": "The task or question you want the Oracle to help with. Be specific about what kind of guidance, review, or planning you need.",
            "type": "string",
        },
        "description": {
            "description": "A short (3-5 word) description of the task",
            "type": "string",
        },
    },
    "required": ["task", "description"],
    "type": "object",
}


def _oracle_prompt_builder(args: dict[str, Any]) -> str:
    """Build the Oracle prompt from tool arguments."""
    context = args.get("context", "")
    task = args.get("task", "")
    files = args.get("files", [])

    prompt = f"""\
Context: {context}
Task: {task}\
"""
    if files:
        files_str = "\n".join(f"@{file}" for file in files)
        prompt += f"\nRelated files to review:\n{files_str}"
    return prompt


register_sub_agent(
    SubAgentProfile(
        name="Oracle",
        description=ORACLE_DESCRIPTION,
        parameters=ORACLE_PARAMETERS,
        prompt_file="prompts/prompt-sub-agent-oracle.md",
        tool_set=(tools.READ, tools.BASH),
        prompt_builder=_oracle_prompt_builder,
        active_form="Consulting Oracle",
        target_model_filter=lambda model: ("gpt-5" not in model) and ("gemini-3" not in model),
    )
)
