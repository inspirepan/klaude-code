import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..tui import ColorStyle, Text, console
from ..utils.exception import format_exception


class MCPServerConfig(BaseModel):
    """MCP server configuration"""

    command: str = Field(..., description='Server startup command')
    args: Optional[List[str]] = Field(default=None, description='Command arguments')
    env: Optional[Dict[str, str]] = Field(default=None, description='Environment variables')


class MCPConfig(BaseModel):
    """MCP configuration model"""

    mcpServers: Dict[str, MCPServerConfig] = Field(default_factory=dict, description='MCP server configurations')


class MCPConfigManager:
    """MCP configuration manager"""

    def __init__(self, work_dir: str = None):
        self.work_dir = Path(work_dir) if work_dir else Path.cwd()
        self.config_path = self.work_dir / '.klaude' / 'mcp.json'
        self._config: Optional[MCPConfig] = None

    def get_config_path(self) -> Path:
        """Get MCP configuration file path"""
        return self.config_path

    def load_config(self) -> MCPConfig:
        """Load MCP configuration"""
        if self._config is not None:
            return self._config

        if not self.config_path.exists():
            self._config = MCPConfig()
            return self._config

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                self._config = MCPConfig.model_validate(config_data)
                return self._config
        except (json.JSONDecodeError, IOError) as e:
            console.print(Text(f'Warning: Failed to load MCP config: {format_exception(e)}', style=ColorStyle.WARNING))
            self._config = MCPConfig()
            return self._config

    def save_config(self, config: Optional[MCPConfig] = None) -> bool:
        """Save MCP configuration"""
        if config is None:
            config = self._config or MCPConfig()

        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)
            self._config = config
            return True
        except (IOError, OSError) as e:
            console.print(Text(f'Error: Failed to save MCP config: {format_exception(e)}', style=ColorStyle.ERROR))
            return False

    def add_server(self, name: str, command: str, args: List[str] = None, env: Dict[str, str] = None) -> bool:
        """Add MCP server"""
        config = self.load_config()

        if name in config.mcpServers:
            console.print(Text(f'Server "{name}" already exists', style=ColorStyle.WARNING))
            return False

        config.mcpServers[name] = MCPServerConfig(command=command, args=args, env=env)

        return self.save_config(config)

    def remove_server(self, name: str) -> bool:
        """Remove MCP server"""
        config = self.load_config()

        if name not in config.mcpServers:
            console.print(Text(f'Server "{name}" not found', style=ColorStyle.ERROR))
            return False

        del config.mcpServers[name]
        return self.save_config(config)

    def create_example_config(self) -> bool:
        """Create example MCP configuration"""
        example_config = MCPConfig(
            mcpServers={
                'fetch': MCPServerConfig(command='uvx', args=['mcp-server-fetch']),
            }
        )

        return self.save_config(example_config)

    def edit_config_file(self):
        """Edit MCP configuration file"""
        if not self.config_path.exists():
            self.create_example_config()

        console.print(Text(f'Opening MCP config file: {self.config_path}', style=ColorStyle.SUCCESS))

        import sys

        editor = os.getenv('EDITOR', 'vi' if sys.platform != 'darwin' else 'open')
        os.system(f'{editor} {self.config_path}')
