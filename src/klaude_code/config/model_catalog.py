from klaude_code.config.config import ModelEntry
from klaude_code.config.formatters import format_model_params
from klaude_code.protocol.model_catalog import ModelCatalogEntry


def build_model_catalog_entry(entry: ModelEntry) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        selector=entry.selector,
        model_name=entry.model_name,
        provider=entry.provider,
        model_id=entry.model_id,
        model_alias=entry.model_alias,
        params=format_model_params(entry),
    )
