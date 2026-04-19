# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from google.auth import load_credentials_from_file
from google.genai import Client
from google.genai.types import HttpOptions

from klaude_code.const import LLM_HTTP_TIMEOUT_TOTAL
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.google.client import GoogleClient
from klaude_code.llm.registry import register
from klaude_code.protocol import llm_param

_GOOGLE_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


@register(llm_param.LLMClientProtocol.GOOGLE_VERTEX)
class GoogleVertexClient(GoogleClient):
    def __init__(self, config: llm_param.LLMConfigParameter):
        LLMClientABC.__init__(self, config)

        credentials = None
        if config.google_application_credentials:
            credentials, _ = load_credentials_from_file(
                config.google_application_credentials,
                scopes=[_GOOGLE_CLOUD_PLATFORM_SCOPE],
            )

        http_options = HttpOptions(timeout=int(LLM_HTTP_TIMEOUT_TOTAL * 1000))
        if config.base_url:
            http_options = HttpOptions(
                base_url=str(config.base_url),
                api_version="",
                timeout=int(LLM_HTTP_TIMEOUT_TOTAL * 1000),
            )

        self.client = Client(
            vertexai=True,
            credentials=credentials,
            project=config.google_cloud_project,
            location=config.google_cloud_location,
            http_options=http_options,
        )
