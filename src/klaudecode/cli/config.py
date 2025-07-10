import typer

from ..config import ConfigManager, ConfigModel, GlobalConfigSource
from ..tui import console


def setup_config(**kwargs) -> ConfigModel:
    config_manager = ConfigManager.setup(**kwargs)
    config_model = config_manager.get_config_model()
    if hasattr(config_model, 'theme') and config_model.theme:
        console.set_theme(config_model.theme.value)
    return config_model


config_app = typer.Typer(help='Manage global configuration', invoke_without_command=True)


@config_app.callback()
def config_callback(ctx: typer.Context):
    """Manage global configuration"""
    if ctx.invoked_subcommand is None:
        # Default action: show config
        config_show()


@config_app.command('show')
def config_show():
    """
    Show global configuration
    """
    config_manager = ConfigManager.setup()
    console.print(config_manager)


@config_app.command('edit')
def config_edit():
    """
    Init or edit global configuration file
    """
    GlobalConfigSource.edit_config_file()
