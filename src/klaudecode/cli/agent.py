import asyncio
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from ..agent import get_main_agent
from ..message import SystemMessage
from ..prompt.system import STATIC_SYSTEM_PROMPT, get_system_prompt_dynamic_part
from ..session import Session
from ..tui import ColorStyle, Text, console, render_hello, render_logo, render_tips
from ..user_input import user_select
from ..utils.exception import format_exception
from ..utils.str_utils import format_relative_time
from .arg_parse import CLIArgs
from .config import setup_config


async def get_session(args: CLIArgs, config_model) -> Optional[Session]:
    if args.continue_latest:
        session = Session.get_latest_session(Path.cwd())
        if not session:
            console.print(
                Text(f"No session found in {Path.cwd()}", style=ColorStyle.ERROR)
            )
            return None
        session = session.create_new_session()
    elif args.resume:
        sessions = Session.load_session_list(Path.cwd())
        if not sessions or len(sessions) == 0:
            console.print(
                Text(f"No session found in {Path.cwd()}", style=ColorStyle.ERROR)
            )
            return None
        options = []
        for idx, session in enumerate(sessions):
            title_msg = session.get("title_msg", "").replace("\n", " ")
            message_count = session.get("message_count", 0)
            modified_at = format_relative_time(session.get("updated_at"))
            created_at = format_relative_time(session.get("created_at"))
            option = f"{idx + 1:3}.{modified_at:>12}{created_at:>12}{message_count:>12}  {title_msg}"
            options.append(option)
        header = f"{' ' * 4}{'Modified':>12}{'Created':>12}{'# Messages':>12}  Title"
        idx = await user_select(
            options,
            title=header,
        )
        if idx is None:
            return None
        session = Session.load(sessions[idx].get("id"))
    else:
        support_cache_control = "claude" in config_model.model_name.value.lower()
        session = Session(
            work_dir=Path.cwd(),
            messages=[
                SystemMessage(
                    content=STATIC_SYSTEM_PROMPT, cached=support_cache_control
                ),
                SystemMessage(
                    content=get_system_prompt_dynamic_part(
                        Path.cwd(), config_model.model_name.value
                    )
                ),
            ],
        )
    return session


async def agent_async(args: CLIArgs, config_model, unknown_args: List[str]):
    session = await get_session(args, config_model)
    if not session:
        return
    agent = await get_main_agent(session, config=config_model, enable_mcp=args.mcp)
    initial_message = " ".join(unknown_args) if unknown_args else None
    try:
        if args.headless_prompt:
            await agent.headless_run(args.headless_prompt + (initial_message or ""))
        else:
            width, _ = shutil.get_terminal_size()
            has_session = (Path.cwd() / ".klaude" / "sessions").exists()
            auto_show_logo = not has_session
            console.print(render_hello(show_info=not auto_show_logo))
            if (auto_show_logo or args.logo) and width >= 49:
                console.print()
                console.print(render_logo("KLAUDE", ColorStyle.CLAUDE))
                console.print(render_logo("CODE", ColorStyle.CLAUDE))
            console.print()
            console.print(render_tips())
            try:
                await agent.chat_interactive(initial_message=initial_message)
            finally:
                console.print()
                agent.agent_state.print_usage()
                console.print(Text("\nBye!", style=ColorStyle.CLAUDE))
    except KeyboardInterrupt:
        pass


def agent_command(args: CLIArgs, unknown_args: List[str]):
    piped_input = None
    if not sys.stdin.isatty():
        try:
            piped_input = sys.stdin.read().strip()
        except KeyboardInterrupt:
            pass

    print_prompt = args.headless_prompt
    if print_prompt is not None and piped_input:
        print_prompt = f"{print_prompt}\n{piped_input}"
    elif print_prompt is None and piped_input:
        print_prompt = piped_input

    # Update the args model with the processed prompt
    args = args.model_copy(update={"headless_prompt": print_prompt})

    try:
        config_manager = setup_config(
            api_key=args.api_key,
            model_name=args.model,
            base_url=args.base_url,
            model_azure=args.model_azure,
            max_tokens=args.max_tokens,
            enable_thinking=args.thinking,
            api_version=args.api_version,
            extra_header=args.extra_header,
            extra_body=args.extra_body,
            theme=args.theme,
            config_file=args.config,
        )
        config_model = config_manager.get_config_model()
    except ValueError as e:
        console.print(Text.assemble(("Error: ", ColorStyle.ERROR), format_exception(e)))
        sys.exit(1)

    asyncio.run(agent_async(args, config_model, unknown_args))
