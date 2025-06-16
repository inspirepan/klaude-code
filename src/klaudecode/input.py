from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from pydantic import BaseModel


class InputMode(BaseModel):
    prompt: str
    placeholder: str
    style: str

    def get_html_prompt(self):
        return HTML(f'<{self.style}>{self.prompt} </{self.style}>')


input_mode_dict = {
    "normal": InputMode(prompt=">", placeholder="", style=""),
    "plan": InputMode(prompt="*", placeholder="type plan...", style="cyan"),
    "bash_mode": InputMode(prompt="!", placeholder="type command...", style="magenta"),
    # "memory_mode": InputMode(prompt="#", placeholder="type memory...", style="blue"),
}

current_input_mode = input_mode_dict["normal"]


def dyn_prompt():
    return current_input_mode.get_html_prompt()


def dyn_placeholder():
    return current_input_mode.placeholder


kb = KeyBindings()
session = PromptSession(
    dyn_prompt,
    placeholder=dyn_placeholder,
    style=current_input_mode.style,
    key_bindings=kb,
    enable_history_search=True,
)
buf = session.default_buffer


@kb.add("!")
def _(event):
    """
    行首输入 '!'：切换到bash模式(一次性); 不把字符写进缓冲区。
    若光标不在行首或缓冲区非空，则正常插入 '!'
    """
    if buf.text == "" and buf.cursor_position == 0:
        current_input_mode = input_mode_dict["bash_mode"]
        event.app.style = current_input_mode.style
        event.app.invalidate()
        return
    # 否则按普通字符插入
    buf.insert_text("!")


@kb.add("*")
def _(event):
    if buf.text == "" and buf.cursor_position == 0:
        current_input_mode = input_mode_dict["plan"]
        event.app.style = current_input_mode.style
        event.app.invalidate()
        return
    buf.insert_text("*")

@kb.add("backspace")
def _(event):
    if (current_input_mode.prompt in ["!", "*"]) and buf.text == "" and buf.cursor_position == 0:
        current_input_mode = input_mode_dict["normal"]
        event.app.style = current_input_mode.style
        event.app.invalidate()
        return
    # 默认退格
    buf.delete_before_cursor()


@kb.add("enter")
def _(event):
    """
    检查是否以反斜杠结尾：
    - 如果是，则删除反斜杠并插入换行符继续编辑
    - 如果不是，则正常提交输入
    """
    text = buf.text
    if text.endswith("\\"):
        # 删除末尾的反斜杠
        buf.delete_before_cursor()
        # 插入换行符
        buf.insert_text("\n")
    else:
        # 正常提交
        event.app.exit(result=buf.text)