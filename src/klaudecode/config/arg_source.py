from typing import Optional

from .model import ConfigModel, parse_json_string
from .source import ConfigSource


class ArgConfigSource(ConfigSource):
    """CLI argument configuration"""

    source = 'cli'

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        model_azure: Optional[bool] = None,
        max_tokens: Optional[int] = None,
        context_window_threshold: Optional[int] = None,
        extra_header: Optional[str] = None,
        extra_body: Optional[str] = None,
        enable_thinking: Optional[bool] = None,
        api_version: Optional[str] = None,
        theme: Optional[str] = None,
    ):
        super().__init__(self.source)
        # Parse JSON strings for extra_header and extra_body
        parsed_extra_header = parse_json_string(extra_header) if extra_header else None
        parsed_extra_body = parse_json_string(extra_body) if extra_body else None

        self.config_model = ConfigModel(
            source=self.source,
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            model_azure=model_azure,
            max_tokens=max_tokens,
            context_window_threshold=context_window_threshold,
            extra_header=parsed_extra_header,
            extra_body=parsed_extra_body,
            enable_thinking=enable_thinking,
            api_version=api_version,
            theme=theme,
        )
