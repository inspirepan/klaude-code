Launch a new agent to handle complex, multi-step tasks autonomously.

The Agent tool launches specialized agents (subprocesses) that autonomously handle complex tasks. Each agent type has specific capabilities and tools available to it.

When using the Agent tool, you must specify a `type` parameter to select which agent type to use.

Available agent types and the tools they have access to:

${types_section}

Available model override options:

${model_selection_guide}

Execution model:
- Each agent invocation creates a fresh, isolated session. Agents are stateless and one-shot: they run to completion and are then discarded.
- There is no way to resume, continue, or send follow-up messages to a previously launched agent.
- The agent's final text output is returned as the tool result. Internal tool calls and intermediate reasoning are not visible to the caller.
- If you need to iterate on an agent's output, launch a new agent with an updated prompt that includes the previous result.

Usage notes:
- Launch independent agents concurrently by putting multiple Agent tool calls in a single message.
- The agent cannot see the conversation or infer the user's intent. Give it a self-contained prompt: the goal, whether you want code written or just research, the deliverables, and how to validate them.
- When asking a sub-agent to execute a skill, include the skill's full `location` and `base_dir` in your prompt. Do not assume the skill content is already loaded; the sub-agent still needs the concrete path context to read and apply it.
- For non-trivial code review requests, launch `code-reviewer` and `code-maintenance-reviewer` concurrently, then synthesize their findings yourself; correctness findings outrank maintenance ones. Both take the same prompt: background on what the user asked for and the intent behind the changes, a shell command that shows the diff, and the key changed files. For a follow-up review, add the prior findings and scope the diff command to the fix commits.
- After fixing review findings, validate the fixes yourself with targeted tests and direct diff inspection rather than launching a follow-up reviewer; re-run only the reviewer responsible for a finding when the fix is high-risk or hard to verify.

