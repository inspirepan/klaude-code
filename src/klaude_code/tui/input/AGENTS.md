# tui/input Module

REPL input handling: key bindings, paste/drag-drop conversion, and image attachment.

## Data Flow

```
User Input (keyboard/paste/drag)
    -> key_bindings.py (event dispatch)
    -> [convert/fold] -> buffer text with markers
    -> Enter (steering) / Alt+Enter (follow-up) -> expand markers, write history
    -> iter_inputs() -> extract images -> UserInputPayload
```

Both submit keys use the same validation and command flow. The delivery marker
is captured for one payload and reset immediately; queue-edit splits preserve it.
Shift+Enter, ctrl-j, and existing backslash handling still insert newlines.

## Marker Syntax

| Marker | Purpose |
|--------|---------|
| `@<path>` | File/directory reference (triggers ReadTool) |
| `[image <path>]` | Image attachment (encoded on submit) |
| `[paste #N ...]` | Folded multi-line paste (expanded on submit) |

## Files

| File | Responsibility |
|------|----------------|
| `key_bindings.py` | Keyboard/paste event handlers; dispatches to converters; `copy_to_clipboard()` |
| `prompt_toolkit.py` | PromptSession setup; `iter_inputs()` submit flow |
| `drag_drop.py` | `file://` URI and path list to `@`/`[image]` conversion |
| `images.py` | Image handling: marker syntax, ctrl-v capture, `extract_images_from_text()` |
| `paste.py` | `[paste #N ...]` fold/expand for large pastes |
| `completers.py` | `@`/`/` completion providers |

## Special Syntax Features (`@file`, `/skill`)

These features span three modules that must stay in sync:

| Stage | Module | Responsibility |
|-------|--------|----------------|
| Input | `completers.py` | Autocomplete paths/skills as user types |
| Display | `components/user_input.py` | Highlight syntax in rendered messages |
| Action | `agent/attachments/` | Inject file content / load skill for LLM |

When adding or modifying syntax (e.g., new prefix like `#tag`), update all three.
