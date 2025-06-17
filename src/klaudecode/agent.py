from typing import Optional, Tuple, List

from .session import Session
from .input import InputSession, UserInput, Commands
from .message import BasicMessage, SystemMessage, UserMessage, AIMessage, ToolMessage
from .tui import console, render_message
from .llm import AgentLLM
from .config import ConfigManager

DEFAULT_MAX_STEPS = 80
INTERACTIVE_MAX_STEPS = 100
TOKEN_WARNING_THRESHOLD = 0.8
TODO_SUGGESTION_LENGTH_THRESHOLD = 40


class Agent:
    def __init__(
        self,
        session: Session,
        config: ConfigManager,
        name: Optional[str] = None,
        with_agent_tool: bool = False,
        with_todo_tool: bool = False,
    ):
        self.session: Session = session
        self.name = name
        self.input_session = InputSession(session.work_dir)
        self.print_trace = True

    async def chat_interactive(self):
        while True:
            user_input: UserInput = await self.input_session.prompt_async()
            user_raw, command_output, need_agent_run = self.handle_user_command(user_input)
            self.append_message(UserMessage(content=command_output, mode=user_input.mode), print_msg=False)
            if need_agent_run:
                if not command_output:
                    continue
                await self.run(max_steps=INTERACTIVE_MAX_STEPS)

    async def run(self, max_steps: int = DEFAULT_MAX_STEPS):
        for _ in range(max_steps):
            llm_response = await AgentLLM.call([m.to_openai() for m in self.session.messages])
            ai_message: AIMessage = AIMessage.from_llm_response(llm_response)
            self.append_message(ai_message)
            if llm_response.finish_reason == "stop":
                return llm_response.content
            if llm_response.finish_reason == "tool_calls" or len(llm_response.tool_calls) > 0:
                await self.handle_tool_calls(ai_message)

        max_step_msg = f"Max steps {max_steps} reached"
        console.print(render_message(max_step_msg, mark_style="blue"))
        return max_step_msg

    def append_message(self, msg: BasicMessage, print_msg=True):
        self.session.append_message(msg)
        if self.print_trace:
            if print_msg:
                console.print(msg)
            console.print()

    def handle_user_command(self, user_input: UserInput) -> Tuple[str, str, bool]:
        if not user_input.command:
            return user_input.content, user_input.content, True
        return user_input.content, user_input.content, True
        # if user_input.command == Commands.STATUS:

    def handle_tool_calls(self, ai_message: AIMessage):
        pass
