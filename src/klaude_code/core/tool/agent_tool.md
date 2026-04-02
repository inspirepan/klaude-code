Launch a new agent to handle complex, multi-step tasks autonomously.

The Agent tool launches specialized agents (subprocesses) that autonomously handle complex tasks. Each agent type has specific capabilities and tools available to it.

When using the Agent tool, you must specify a `type` parameter to select which agent type to use.

Available agent types and the tools they have access to:

${types_section}

Execution model:
- Each agent invocation creates a fresh, isolated session. Agents are stateless and one-shot: they run to completion and are then discarded.
- There is no way to resume, continue, or send follow-up messages to a previously launched agent.
- The agent's final text output is returned as the tool result. Internal tool calls and intermediate reasoning are not visible to the caller.
- If you need to iterate on an agent's output, launch a new agent with an updated prompt that includes the previous result.

Usage notes:
- Always include a short description (3-5 words) summarizing what the agent will do
- Launch multiple agents concurrently whenever possible, to maximize performance; to do that, use a single message with multiple tool uses
- Clearly tell the agent whether you expect it to write code or just to do research (search, file reads, etc.), since it is not aware of the user's intent
- Provide clear, detailed prompts so the agent can work autonomously and return exactly the information you need.
- When asking a sub-agent to execute a skill, include the skill's full `location` and `base_dir` in your prompt, since sub-agents do not automatically load `<available_skills>` metadata.
- If the agent description mentions that it should be used proactively, then you should try your best to use it without the user having to ask for it first. Use your judgement.
- If the user specifies that they want you to run agents "in parallel", you MUST send a single message with multiple Agent tool use content blocks. For example, if you need to launch both a code-reviewer agent and a test-runner agent in parallel, send a single message with both tool calls.

