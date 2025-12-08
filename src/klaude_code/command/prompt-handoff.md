---
description: Write a HANDOFF.md for another agent to continue the conversation
from: amp-cli https://ampcode.com/manual#handoff
---

Write a HANDOFF.md file in the current working directory for another agent to continue this conversation.

Extract relevant context from the conversation above to facilitate continuing this work. Write from my perspective (first person: "I did...", "I told you...").

Consider what would be useful to know based on my request below. Relevant questions include:
- What did I just do or implement?
- What instructions did I give you that are still relevant (e.g., follow patterns in the codebase)?
- Did I provide a plan or spec that should be included?
- What important information did I share (certain libraries, patterns, constraints, preferences)?
- What key technical details did I discover (APIs, methods, patterns)?
- What caveats, limitations, or open questions remain?

Extract only what matters for the specific request below. Skip irrelevant questions. Choose an appropriate length based on the complexity of the request.

Focus on capabilities and behavior, not file-by-file changes. Avoid excessive implementation details (variable names, storage keys, constants) unless critical.

Format: Plain text with bullets. No markdown headers, no bold/italic, no code fences. Use workspace-relative paths for files.

List file or directory paths (workspace-relative) relevant to accomplishing the goal in the following format:
<example>
@src/project/main.py
@src/project/llm/
</example>

My request:
$ARGUMENTS

<system>If the request section is empty, ask for clarification about the goal</system>