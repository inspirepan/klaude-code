# Concepts
- Session: A conversation between user and agent
  - SubAgents has their own conversation history and session
- Task: When a user provides an input, the Agent executes ReAct until there are no more tool calls. This entire process constitutes a Task
- Turn: Each round where the Agent responds with Reasoning, Text, and ToolCalls. If there are ToolCalls, the execution of the toolcall and generation of ToolResults is considered one Turn
- Response: Each call to the LLM API is considered a Response


- `src/protocol/model.py`: Communication structure definitions between the Agent execution layer and LLMClient, also serving as the persistent structure for conversations, base class is `model.ConversationItem`
- `src/protocol/events.py`: Event definitions sent from the Agent execution layer to the UI layer, base class is `events.Event`
- `src/protocol/op.py`: Operation definitions sent from the UI layer to the Agent execution layer.


# Dev

## Pyright

type check mode: strict

## Format
```
isort . && ruff format
```
