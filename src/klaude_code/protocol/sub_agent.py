from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from klaude_code.protocol import tools

if TYPE_CHECKING:
    from klaude_code.protocol import model

AvailabilityPredicate = Callable[[str], bool]
PromptBuilder = Callable[[dict[str, Any]], str]


@dataclass
class SubAgentResult:
    task_result: str
    session_id: str
    error: bool = False
    task_metadata: model.TaskMetadata | None = None


def _default_prompt_builder(args: dict[str, Any]) -> str:
    """Default prompt builder that just returns the 'prompt' field."""
    return args.get("prompt", "")


@dataclass(frozen=True)
class SubAgentProfile:
    """Metadata describing a sub agent and how it integrates with the system.

    This dataclass contains all the information needed to:
    1. Register the sub agent with the system
    2. Generate the tool schema for the main agent
    3. Build the prompt for the sub agent
    """

    # Identity - single name used for type, tool_name, config_key, and prompt_key
    name: str  # e.g., "Task", "Oracle", "Explore"

    # Tool schema
    description: str  # Tool description shown to the main agent
    parameters: dict[str, Any] = field(
        default_factory=lambda: dict[str, Any](), hash=False
    )  # JSON Schema for tool parameters

    # Sub agent configuration
    tool_set: tuple[str, ...] = ()  # Tools available to this sub agent
    prompt_builder: PromptBuilder = _default_prompt_builder  # Builds the sub agent prompt from tool arguments

    # UI display
    active_form: str = ""  # Active form for spinner status (e.g., "Tasking", "Exploring")

    # Availability
    enabled_by_default: bool = True
    show_in_main_agent: bool = True
    target_model_filter: AvailabilityPredicate | None = None

    def enabled_for_model(self, model_name: str | None) -> bool:
        if not self.enabled_by_default:
            return False
        if model_name is None or self.target_model_filter is None:
            return True
        return self.target_model_filter(model_name)


_PROFILES: dict[str, SubAgentProfile] = {}


def register_sub_agent(profile: SubAgentProfile) -> None:
    if profile.name in _PROFILES:
        raise ValueError(f"Duplicate sub agent profile: {profile.name}")
    _PROFILES[profile.name] = profile


def get_sub_agent_profile(sub_agent_type: tools.SubAgentType) -> SubAgentProfile:
    try:
        return _PROFILES[sub_agent_type]
    except KeyError as exc:
        raise KeyError(f"Unknown sub agent type: {sub_agent_type}") from exc


def iter_sub_agent_profiles(enabled_only: bool = False, model_name: str | None = None) -> list[SubAgentProfile]:
    profiles = list(_PROFILES.values())
    if not enabled_only:
        return profiles
    return [p for p in profiles if p.enabled_for_model(model_name)]


def get_sub_agent_profile_by_tool(tool_name: str) -> SubAgentProfile | None:
    return _PROFILES.get(tool_name)


def is_sub_agent_tool(tool_name: str) -> bool:
    return tool_name in _PROFILES


def sub_agent_tool_names(enabled_only: bool = False, model_name: str | None = None) -> list[str]:
    return [
        profile.name
        for profile in iter_sub_agent_profiles(enabled_only=enabled_only, model_name=model_name)
        if profile.show_in_main_agent
    ]


# -----------------------------------------------------------------------------
# Sub Agent Definitions
# -----------------------------------------------------------------------------

TASK_DESCRIPTION = """\
Launch a new agent to handle complex, multi-step tasks autonomously. \

When NOT to use the Task tool:
- If you want to read a specific file path, use the Read or Bash tool for `rg` instead of the Task tool, to find the match more quickly
- If you are searching for a specific class definition like "class Foo", use the Bash tool for `rg` instead, to find the match more quickly
- If you are searching for code within a specific file or set of 2-3 files, use the Read tool instead of the Task tool, to find the match more quickly
- Other tasks that are not related to the agent descriptions above

Usage notes:
- Launch multiple agents concurrently whenever possible, to maximize performance; to do that, use a single message with multiple tool uses
- When the agent is done, it will return a single message back to you. The result returned by the agent is not visible to the user. To show the user the result, you should send a text message back to the user with a concise summary of the result.
- Each agent invocation is stateless. You will not be able to send additional messages to the agent, nor will the agent be able to communicate with you outside of its final report. Therefore, your prompt should contain a highly detailed task description for the agent to perform autonomously and you should specify exactly what information the agent should return back to you in its final and only message to you.
- The agent's outputs should generally be trusted
- Clearly tell the agent whether you expect it to write code or just to do research (search, file reads, etc.), since it is not aware of the user's intent
- If the agent description mentions that it should be used proactively, then you should try your best to use it without the user having to ask for it first. Use your judgement.
- If the user specifies that they want you to run agents "in parallel", you MUST send a single message with multiple Task tool use content blocks. For example, if you need to launch both a code-reviewer agent and a test-runner agent in parallel, send a single message with both tool calls.\
"""

TASK_PARAMETERS = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "A short (3-5 word) description of the task",
        },
        "prompt": {
            "type": "string",
            "description": "The task for the agent to perform",
        },
    },
    "required": ["description", "prompt"],
    "additionalProperties": False,
}

register_sub_agent(
    SubAgentProfile(
        name="Task",
        description=TASK_DESCRIPTION,
        parameters=TASK_PARAMETERS,
        tool_set=(tools.BASH, tools.READ, tools.EDIT, tools.WRITE),
        active_form="Tasking",
    )
)


# -----------------------------------------------------------------------------
# Oracle Sub Agent
# -----------------------------------------------------------------------------

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

    prompt = f"""Context: {context}

Task: {task}
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
        tool_set=(tools.READ, tools.BASH),
        prompt_builder=_oracle_prompt_builder,
        active_form="Consulting Oracle",
        target_model_filter=lambda model: ("gpt-5" not in model) and ("gemini-3" not in model),
    )
)


# -----------------------------------------------------------------------------
# Explore Sub Agent
# -----------------------------------------------------------------------------

EXPLORE_DESCRIPTION = """\
Spin up a fast agent specialized for exploring codebases. Use this when you need to quickly find files by patterns (eg. "src/components/**/*.tsx"), \
search code for keywords (eg. "API endpoints"), or answer questions about the codebase (eg. "how do API endpoints work?")\
When calling this agent, specify the desired thoroughness level: "quick" for basic searches, "medium" for moderate exploration, or "very thorough" for comprehensive analysis across multiple locations and naming conventions.
Always spawn multiple search agents in parallel to maximise speed.\
"""

EXPLORE_PARAMETERS = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "Short (3-5 words) label for the exploration goal",
        },
        "prompt": {
            "type": "string",
            "description": "The task for the agent to perform",
        },
        "thoroughness": {
            "type": "string",
            "enum": ["quick", "medium", "very thorough"],
            "description": "Controls how deep the sub-agent should search the repo",
        },
    },
    "required": ["description", "prompt"],
    "additionalProperties": False,
}


def _explore_prompt_builder(args: dict[str, Any]) -> str:
    """Build the Explore prompt from tool arguments."""
    prompt = args.get("prompt", "").strip()
    thoroughness = args.get("thoroughness", "medium")
    return f"{prompt}\nthoroughness: {thoroughness}"


register_sub_agent(
    SubAgentProfile(
        name="Explore",
        description=EXPLORE_DESCRIPTION,
        parameters=EXPLORE_PARAMETERS,
        tool_set=(tools.BASH, tools.READ),
        prompt_builder=_explore_prompt_builder,
        active_form="Exploring",
        target_model_filter=lambda model: ("haiku" not in model) and ("kimi" not in model) and ("grok" not in model),
    )
)


# -----------------------------------------------------------------------------
# WebFetchAgent Sub Agent
# -----------------------------------------------------------------------------

WEB_FETCH_AGENT_DESCRIPTION = """\
Launch a sub-agent to fetch and analyze web content. Use this when you need to:
- Retrieve and extract information from a webpage
- Analyze web page content based on specific instructions
- Get structured data from URLs

The agent will fetch the URL content, handle HTML-to-Markdown conversion automatically, \
and can use tools like rg to search through large responses that were truncated and saved to files.

Usage notes:
- Provide a clear prompt describing what information to extract or analyze
- The agent will return a summary of the findings
- For large web pages, the content may be truncated and saved to a file; the agent can search through it\
"""

WEB_FETCH_AGENT_PARAMETERS = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "A short (3-5 word) description of the task",
        },
        "url": {
            "type": "string",
            "description": "The URL to fetch and analyze",
        },
        "prompt": {
            "type": "string",
            "description": "Instructions for analyzing or extracting content from the web page",
        },
    },
    "required": ["description", "url", "prompt"],
    "additionalProperties": False,
}


def _web_fetch_prompt_builder(args: dict[str, Any]) -> str:
    """Build the WebFetchAgent prompt from tool arguments."""
    url = args.get("url", "")
    prompt = args.get("prompt", "")
    return f"URL to fetch: {url}\nTask: {prompt}"


register_sub_agent(
    SubAgentProfile(
        name="WebFetchAgent",
        description=WEB_FETCH_AGENT_DESCRIPTION,
        parameters=WEB_FETCH_AGENT_PARAMETERS,
        tool_set=(tools.BASH, tools.READ, tools.WEB_FETCH),
        prompt_builder=_web_fetch_prompt_builder,
        active_form="Fetching Web",
    )
)
