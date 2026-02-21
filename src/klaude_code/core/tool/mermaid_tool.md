Renders a Mermaid diagram from the provided code.

PROACTIVELY USE DIAGRAMS when they would better convey information than prose alone. The diagrams produced by this tool are shown to the user..

You should create diagrams WITHOUT being explicitly asked in these scenarios:
- When explaining system architecture or component relationships
- When describing workflows, data flows, or user journeys
- When explaining algorithms or complex processes
- When illustrating class hierarchies or entity relationships
- When showing state transitions or event sequences

Diagrams are especially valuable for visualizing:
- Application architecture and dependencies
- API interactions and data flow
- Component hierarchies and relationships
- State machines and transitions
- Sequence and timing of operations
- Decision trees and conditional logic

# Syntax
- ALWAYS wrap node labels in double quotes, especially when they contain spaces, special characters, or non-ASCII text
- This applies to all node types: regular nodes, subgraph titles, and edge labels

Examples:
```mermaid
graph LR
  A["User Input"] --> B["Process Data"]
  B --> C["Output Result"]
```

```mermaid
flowchart TD
  subgraph auth["Authentication Module"]
    login["Login Service"]
    oauth["OAuth Provider"]
  end
```

```mermaid
sequenceDiagram
  participant client as "Web Client"
  participant server as "API Server"
  client ->> server: "Send Request"
```

# Styling
- When defining custom classDefs, always define fill color, stroke color, and text color ("fill", "stroke", "color") explicitly
- Use colors to distinguish node types and improve readability

## Color Palette
- Cyan #e0f0f0 - information, data flow
- Green #e0f0e0 - success, completion
- Blue #e0e8f5 - primary actions, main flow
- Purple #ede0f5 - highlights, special nodes
- Orange #f5ebe0 - warnings, pending
- Red #f5e0e0 - errors, critical
- Grey #e8e8e8 - neutral elements
- Yellow #f5f5e0 - attention, notes

Example:
```mermaid
classDef primary fill:#e0e8f5,stroke:#3078C5,color:#1a1a1a
classDef success fill:#e0f0e0,stroke:#00875f,color:#1a1a1a
```
