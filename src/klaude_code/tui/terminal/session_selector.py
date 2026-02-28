from klaude_code.log import log
from klaude_code.session.selector import build_session_select_options, format_user_messages_display
from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, SelectItem, select_one


def select_session_sync(session_ids: list[str] | None = None) -> str | None:
    """Interactive session selection (sync version for asyncio.to_thread).

    Args:
        session_ids: Optional list of session IDs to filter. If provided, only show these sessions.
    """
    options = build_session_select_options()
    if session_ids is not None:
        session_id_set = set(session_ids)
        options = [opt for opt in options if opt.session_id in session_id_set]
    if not options:
        log("No sessions found for this project.")
        return None

    items: list[SelectItem[str]] = []
    for idx, opt in enumerate(options, 1):
        display_msgs = format_user_messages_display(opt.user_messages)
        title: list[tuple[str, str]] = []
        title.append(("fg:ansibrightblack", f"{idx:2}. "))
        title.append(("class:meta", f"{opt.relative_time} · {opt.messages_count} · {opt.model_name}"))
        title.append(("fg:ansibrightblack dim", f" · {opt.session_id}\n"))
        for i, msg in enumerate(display_msgs):
            is_last = i == len(display_msgs) - 1
            if msg == "⋮":
                title.append(("class:msg", f"    {msg}\n"))
            else:
                prefix = "╰─" if is_last else "├─"
                title.append(("fg:ansibrightblack dim", f"    {prefix} "))
                title.append(("class:msg", f"{msg}\n"))
        title.append(("", "\n"))

        search_text = " ".join(opt.user_messages) + f" {opt.model_name} {opt.session_id}"
        items.append(
            SelectItem(
                title=title,
                value=opt.session_id,
                search_text=search_text,
            )
        )

    try:
        return select_one(
            message="Select a session to resume:",
            items=items,
            pointer="→",
            style=DEFAULT_PICKER_STYLE,
        )
    except KeyboardInterrupt:
        return None
