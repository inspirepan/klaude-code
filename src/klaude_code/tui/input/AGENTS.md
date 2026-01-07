# tui/input Module

REPL input handling: key bindings, paste/drag-drop conversion, and image attachment.

## Data Flow

```
User Input (keyboard/paste/drag)
    -> key_bindings.py (event dispatch)
    -> [convert/fold] -> buffer text with markers
    -> Enter submit -> expand markers, write history
    -> iter_inputs() -> extract images -> UserInputPayload
```

## Marker Syntax

| Marker | Purpose |
|--------|---------|
| `@<path>` | File/directory reference (triggers ReadTool) |
| `[image <path>]` | Image attachment (encoded on submit) |
| `[paste #N ...]` | Folded multi-line paste (expanded on submit) |

## Files

| File | Responsibility |
|------|----------------|
| `key_bindings.py` | Keyboard/paste event handlers; dispatches to converters |
| `prompt_toolkit.py` | PromptSession setup; `iter_inputs()` submit flow |
| `drag_drop.py` | `file://` URI and path list to `@`/`[image]` conversion |
| `clipboard.py` | Ctrl+V image capture; `extract_images_from_text()` |
| `image_markers.py` | `[image ...]` syntax: regex, format, parse |
| `paste.py` | `[paste #N ...]` fold/expand for large pastes |
| `completers.py` | `@`/`/`/`$` completion providers |
