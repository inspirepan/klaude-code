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
- Reviewer prompts (`code-reviewer`, `code-maintenance-reviewer`) carry three things: what the change is meant to do and which behaviors are deliberate (omit arguments that it is correct); a shell command that prints exactly the hunks under review -- `git diff HEAD -- <paths>`, a commit range if the work was committed, or the `jj diff` equivalent -- naming which hunks belong to this task when other edits share those files; and the key changed files. Each reviewer is told the other is running on the same diff, so keep each prompt to its own remit -- asking `code-maintenance-reviewer` about fragile logic or behavioral consequences just makes it duplicate `code-reviewer`. For a follow-up review, add the prior findings and scope the diff to the fix: a commit range if you committed, otherwise the files and functions the fix touched.
- When the user asks for a review of non-trivial changes, launch both reviewers concurrently, then synthesize their findings yourself; correctness findings outrank maintenance ones. When reviewing your own changes, `code-reviewer` is the required one; run alone it reports correctness only, which is the intended trade-off. Add `code-maintenance-reviewer` alongside it when the change introduces new helpers, modules, or abstractions.

