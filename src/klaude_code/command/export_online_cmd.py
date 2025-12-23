from __future__ import annotations

import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

from rich.console import Console
from rich.text import Text

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model
from klaude_code.session.export import build_export_html


class ExportOnlineCommand(CommandABC):
    """Export and deploy the current session to surge.sh as a static webpage."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.EXPORT_ONLINE

    @property
    def summary(self) -> str:
        return "Export and deploy session to surge.sh"

    @property
    def support_addition_params(self) -> bool:
        return False

    @property
    def is_interactive(self) -> bool:
        return False

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        del user_input  # unused
        # Check if npx or surge is available
        surge_cmd = self._get_surge_command()
        if not surge_cmd:
            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content="surge.sh CLI not found. Install with: npm install -g surge",
                    command_output=model.CommandOutput(command_name=self.name, is_error=True),
                ),
            )
            return CommandResult(events=[event])

        try:
            console = Console()
            # Check login status inside status context since npx surge whoami can be slow
            with console.status(Text("Checking surge.sh login status...", style="dim"), spinner_style="dim"):
                logged_in = self._is_surge_logged_in(surge_cmd)

            if not logged_in:
                login_cmd = " ".join([*surge_cmd, "login"])
                event = events.DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=model.DeveloperMessageItem(
                        content=f"Not logged in to surge.sh. Please run: {login_cmd}",
                        command_output=model.CommandOutput(command_name=self.name, is_error=True),
                    ),
                )
                return CommandResult(events=[event])

            with console.status(Text("Deploying to surge.sh...", style="dim"), spinner_style="dim"):
                html_doc = self._build_html(agent)
                domain = self._generate_domain()
                url = self._deploy_to_surge(surge_cmd, html_doc, domain)

            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content=f"Session deployed to: {url}",
                    command_output=model.CommandOutput(command_name=self.name),
                ),
            )
            return CommandResult(events=[event])
        except Exception as exc:
            import traceback

            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content=f"Failed to deploy session: {exc}\n{traceback.format_exc()}",
                    command_output=model.CommandOutput(command_name=self.name, is_error=True),
                ),
            )
            return CommandResult(events=[event])

    def _get_surge_command(self) -> list[str] | None:
        """Check if surge CLI is available, prefer npx if available."""
        # Check for npx first (more common)
        if shutil.which("npx"):
            return ["npx", "surge"]
        # Check for globally installed surge
        if shutil.which("surge"):
            return ["surge"]
        return None

    def _is_surge_logged_in(self, surge_cmd: list[str]) -> bool:
        """Check if user is logged in to surge.sh via 'surge whoami'."""
        try:
            cmd = [*surge_cmd, "whoami"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            # If logged in, whoami returns 0 and prints the email
            # If not logged in, it returns non-zero or prints "Not Authenticated"
            if result.returncode != 0:
                return False
            output = (result.stdout + result.stderr).lower()
            if "not authenticated" in output or "not logged in" in output:
                return False
            return bool(result.stdout.strip())
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _generate_domain(self) -> str:
        """Generate a random subdomain for surge.sh."""
        random_suffix = secrets.token_hex(4)
        return f"klaude-session-{random_suffix}.surge.sh"

    def _deploy_to_surge(self, surge_cmd: list[str], html_content: str, domain: str) -> str:
        """Deploy HTML content to surge.sh and return the URL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "index.html"
            html_path.write_text(html_content, encoding="utf-8")

            # Run surge with --domain flag
            cmd = [*surge_cmd, tmpdir, "--domain", domain]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                raise RuntimeError(f"Surge deployment failed: {error_msg}")

            return f"https://{domain}"

    def _build_html(self, agent: Agent) -> str:
        profile = agent.profile
        system_prompt = (profile.system_prompt if profile else "") or ""
        tools = profile.tools if profile else []
        model_name = profile.llm_client.model_name if profile else "unknown"
        return build_export_html(agent.session, system_prompt, tools, model_name)
