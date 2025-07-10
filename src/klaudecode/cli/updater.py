"""Update functionality for klaude-code."""

import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer

try:
    from importlib.metadata import version
except ImportError:
    from importlib_metadata import version

from ..tui import ColorStyle, Text, console
from ..user_input import user_select

update_app = typer.Typer(help='Update commands')


class UpdaterError(Exception):
    """Exception raised during update operations."""

    pass


class KlaudeUpdater:
    """Handles updating klaude-code installations."""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent

    def get_current_version(self) -> Optional[str]:
        """Get the current installed version."""
        try:
            return version('klaude-code')
        except Exception:
            return None

    def get_latest_version(self) -> Optional[str]:
        """Get the latest version from PyPI."""
        try:
            result = subprocess.run(['python', '-m', 'pip', 'index', 'versions', 'klaude-code'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                # Parse the output to get the latest version
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if 'Available versions:' in line:
                        # Extract first version from the list
                        versions_part = line.split('Available versions:')[1].strip()
                        if versions_part:
                            # Get the first version (latest)
                            latest = versions_part.split(',')[0].strip()
                            return latest
            return None
        except Exception:
            return None

    def check_for_updates(self) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Check if updates are available.

        Returns:
            tuple: (has_update, current_version, latest_version)
        """
        is_editable, _ = self.detect_installation_type()

        # For editable installations, check git instead of PyPI
        if is_editable:
            if self.is_git_repository(self.project_root):
                try:
                    # Fetch latest changes without merging
                    subprocess.run(['git', 'fetch'], cwd=self.project_root, capture_output=True, timeout=10)

                    # Check if we're behind origin
                    result = subprocess.run(['git', 'rev-list', '--count', 'HEAD..origin/main'], cwd=self.project_root, capture_output=True, text=True, timeout=10)

                    if result.returncode == 0:
                        commits_behind = int(result.stdout.strip() or '0')
                        return commits_behind > 0, 'editable', f'{commits_behind} commits behind'
                except Exception:
                    pass
            return False, 'editable', 'editable'

        # For regular installations, check PyPI
        current = self.get_current_version()
        latest = self.get_latest_version()

        if current and latest:
            # Simple version comparison (this could be improved with packaging.version)
            has_update = current != latest
            return has_update, current, latest

        return False, current, latest

    async def prompt_for_update(self, current_version: str, latest_version: str) -> bool:
        """
        Prompt user whether they want to update.

        Returns:
            bool: True if user wants to update
        """
        is_editable, _ = self.detect_installation_type()

        if is_editable:
            message = f'New commits available ({latest_version}). Update now?'
        else:
            message = f'Update available: {current_version} → {latest_version}. Update now?'

        console.print(Text(message, style=ColorStyle.INFO))

        options = ['Yes, update now', 'No, skip this time', 'Never ask again']
        choice = await user_select(options, title='Update available')

        if choice is None or choice == 1:  # No or skip
            return False
        elif choice == 2:  # Never ask again
            # TODO: Save preference to config
            console.print(Text('Update checks disabled. Use "klaude update" to update manually.', style=ColorStyle.INFO))
            return False
        else:  # Yes
            return True

    def detect_installation_type(self) -> tuple[bool, Optional[Path]]:
        """
        Detect if this is an editable installation by checking if current file is in project directory.

        Returns:
            tuple: (is_editable, install_location)
        """
        try:
            # Check if we're running from the project source directory
            current_file = Path(__file__).resolve()
            is_editable = self.project_root in current_file.parents or current_file.parent == self.project_root
            return is_editable, self.project_root if is_editable else None
        except Exception:
            return False, None

    def is_git_repository(self, path: Path) -> bool:
        """Check if the given path is a git repository."""
        git_check = subprocess.run(['git', 'rev-parse', '--git-dir'], cwd=path, capture_output=True, text=True)
        return git_check.returncode == 0

    def update_editable_installation(self) -> bool:
        """
        Update editable installation using git pull + uv sync.

        Returns:
            bool: True if successful, False otherwise
        """
        console.print(Text('Detected editable installation. Attempting to update from git...', style=ColorStyle.INFO))

        if not self.is_git_repository(self.project_root):
            console.print(Text('Editable installation detected but not in a git repository.', style=ColorStyle.WARNING))
            console.print(Text('For editable installations, please update manually with "git pull && uv sync"', style=ColorStyle.INFO))
            return False

        # Get current branch and commit before update
        try:
            branch_result = subprocess.run(['git', 'branch', '--show-current'], cwd=self.project_root, capture_output=True, text=True)
            current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else 'unknown'

            commit_result = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=self.project_root, capture_output=True, text=True)
            current_commit = commit_result.stdout.strip() if commit_result.returncode == 0 else 'unknown'

            console.print(Text(f'Current: {current_branch}@{current_commit}', style=ColorStyle.INFO))
        except Exception:
            current_branch = current_commit = 'unknown'

        # Pull latest changes
        result = subprocess.run(['git', 'pull'], cwd=self.project_root, capture_output=True, text=True)
        if result.returncode != 0:
            console.print(Text(f'✗ Git pull failed: {result.stderr}', style=ColorStyle.ERROR))
            return False

        # Get new branch and commit after update
        try:
            branch_result = subprocess.run(['git', 'branch', '--show-current'], cwd=self.project_root, capture_output=True, text=True)
            new_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else 'unknown'

            commit_result = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=self.project_root, capture_output=True, text=True)
            new_commit = commit_result.stdout.strip() if commit_result.returncode == 0 else 'unknown'

            console.print(Text(f'Updated: {new_branch}@{new_commit}', style=ColorStyle.SUCCESS))
        except Exception:
            pass

        console.print(Text('✓ Updated editable installation from git', style=ColorStyle.SUCCESS))

        # Check if dependencies need updating
        sync_result = subprocess.run(['uv', 'sync'], cwd=self.project_root, capture_output=True, text=True)
        if sync_result.returncode == 0:
            console.print(Text('✓ Dependencies synced', style=ColorStyle.SUCCESS))
        else:
            console.print(Text('⚠ Git updated but dependency sync failed. Run "uv sync" manually.', style=ColorStyle.WARNING))

        return True

    def update_with_uv(self) -> bool:
        """
        Update using uv tool upgrade.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            result = subprocess.run(['uv', 'tool', 'upgrade', 'klaude-code'], capture_output=True, text=True)
            if result.returncode == 0:
                console.print(Text('✓ Updated successfully with uv', style=ColorStyle.SUCCESS))
                return True
        except FileNotFoundError:
            pass
        return False

    def update_with_pip(self) -> bool:
        """
        Update using pip install --upgrade.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'klaude-code'], capture_output=True, text=True)
            if result.returncode == 0:
                console.print(Text('✓ Updated successfully with pip', style=ColorStyle.SUCCESS))
                return True
            else:
                console.print(Text(f'✗ Update failed: {result.stderr}', style=ColorStyle.ERROR))
                return False
        except Exception as e:
            from ..utils.exception import format_exception

            console.print(Text(f'✗ Update failed: {format_exception(e)}', style=ColorStyle.ERROR))
            return False

    def update(self) -> bool:
        """
        Main update method that handles all installation types.

        Returns:
            bool: True if successful, False otherwise
        """
        console.print(Text('Updating klaude-code...', style=ColorStyle.INFO))

        # Check if this is an editable installation
        is_editable, _ = self.detect_installation_type()

        if is_editable:
            return self.update_editable_installation()

        # Try uv first (recommended)
        if self.update_with_uv():
            return True

        # Fallback to pip
        return self.update_with_pip()


def update_klaude_code() -> bool:
    """
    Update klaude-code to the latest version.

    Returns:
        bool: True if successful, False otherwise
    """
    updater = KlaudeUpdater()
    return updater.update()


async def check_and_prompt_update() -> bool:
    """
    Check for updates and prompt user if available.

    Returns:
        bool: True if update was performed, False otherwise
    """
    try:
        updater = KlaudeUpdater()
        has_update, current, latest = updater.check_for_updates()

        if has_update and current and latest:
            should_update = await updater.prompt_for_update(current, latest)
            if should_update:
                console.print(Text('Starting update...', style=ColorStyle.INFO))
                success = updater.update()
                if success:
                    console.print(Text('Update completed! Please restart klaude.', style=ColorStyle.SUCCESS))
                    return True
                else:
                    console.print(Text('Update failed. Continuing with current version.', style=ColorStyle.ERROR))

        return False
    except Exception:
        # Silently fail update checks to not interrupt the main flow
        return False


@update_app.command('update')
def update_command():
    """Update klaude-code to the latest version"""
    update_klaude_code()
