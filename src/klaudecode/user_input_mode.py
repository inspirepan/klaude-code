import asyncio
import signal
import subprocess
from typing import TYPE_CHECKING, Generator

from rich.abc import RichRenderable
from rich.live import Live
from rich.text import Text

from .message import UserMessage, render_message, render_suffix
from .tools.bash import BashTool
from .tui import console
from .user_input import CommandHandleOutput, InputModeCommand, UserInput, register_input_mode

if TYPE_CHECKING:
    from .agent import Agent


# Input Modes
# ---------------------


class PlanMode(InputModeCommand):
    def get_name(self) -> str:
        return 'plan'

    def _get_prompt(self) -> str:
        return '*'

    def _get_color(self) -> str:
        return '#6aa4a5'

    def get_placeholder(self) -> str:
        return 'type to start planning...'

    def get_next_mode_name(self) -> str:
        return 'plan'

    def binding_key(self) -> str:
        return '*'

    # TODO: Implement handle


class BashMode(InputModeCommand):
    def get_name(self) -> str:
        return 'bash'

    def _get_prompt(self) -> str:
        return '!'

    def _get_color(self) -> str:
        return '#ea3386'

    def get_placeholder(self) -> str:
        return 'type a bash command...'

    def binding_key(self) -> str:
        return '!'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent, user_input)
        command = user_input.cleaned_input

        # Safety check
        is_safe, error_msg = BashTool.validate_command_safety(command)
        if not is_safe:
            command_result = f'Error: {error_msg}'
            command_handle_output.user_msg.set_extra_data('command_result', command_result)
            return command_handle_output

        # Execute command and display output in streaming mode
        command_result = await self._execute_command_with_live_output(command)
        command_handle_output.user_msg.set_extra_data('command_result', command_result)
        command_handle_output.need_render_suffix = False
        command_handle_output.need_agent_run = False
        return command_handle_output

    async def _execute_command_with_live_output(self, command: str) -> str:
        """使用 rich.live 流式执行命令并显示输出"""
        output_lines = []
        process = None

        # 创建显示文本
        display_text = Text()

        try:
            # 启动进程
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=0)

            interrupted = False

            def signal_handler(signum, frame):
                nonlocal interrupted
                interrupted = True
                if process and process.poll() is None:
                    try:
                        BashTool._kill_process_tree(process.pid)
                    except Exception:
                        pass

            # 设置信号处理器
            old_handler = signal.signal(signal.SIGINT, signal_handler)

            with Live(render_suffix(display_text), console=console.console, refresh_per_second=10) as live:
                while process.poll() is None and not interrupted:
                    try:
                        # 读取输出
                        output = process.stdout.readline()
                        if output:
                            output_lines.append(output.rstrip())
                            # 更新显示
                            display_text = Text()
                            for line in output_lines[-50:]:  # 只显示最后50行
                                display_text.append(line + '\n')
                            live.update(render_suffix(display_text))
                        else:
                            await asyncio.sleep(0.01)
                    except Exception:
                        break

                # 确保获取剩余输出
                if process.poll() is not None and not interrupted:
                    remaining_output = process.stdout.read()
                    if remaining_output:
                        for line in remaining_output.strip().split('\n'):
                            if line:
                                output_lines.append(line)

                # 最终更新显示
                display_text = Text()
                for line in output_lines:
                    display_text.append(line + '\n')

                if interrupted:
                    display_text.append('\n[Command interrupted by user]', style='bold red')
                elif process.poll() is not None and process.returncode != 0:
                    display_text.append(f'\n[Exit code: {process.returncode}]', style='bold red')

                live.update(render_suffix(display_text))

            # 恢复信号处理器
            signal.signal(signal.SIGINT, old_handler)

        except Exception as e:
            output_lines.append(f'Error executing command: {str(e)}')

        finally:
            # 清理进程
            if process and process.poll() is None:
                try:
                    BashTool._kill_process_tree(process.pid)
                except Exception:
                    pass

        # 返回完整输出
        return '\n'.join(output_lines)

    def render_user_msg(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        yield render_message(user_msg.content, mark='!', style=self._get_color(), mark_style=self._get_color())

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        command_result = user_msg.get_extra_data('command_result')
        if command_result:
            yield render_suffix(command_result)


class MemoryMode(InputModeCommand):
    def get_name(self) -> str:
        return 'memory'

    def _get_prompt(self) -> str:
        return '#'

    def _get_color(self) -> str:
        return '#b3b9f4'

    def get_placeholder(self) -> str:
        return 'type to memorize...'

    def binding_key(self) -> str:
        return '#'

    # TODO: Implement handle


register_input_mode(PlanMode())
register_input_mode(BashMode())
register_input_mode(MemoryMode())
