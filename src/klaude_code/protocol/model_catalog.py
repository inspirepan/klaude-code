from pydantic import BaseModel, Field


class ModelCatalogEntry(BaseModel):
    selector: str
    model_name: str
    provider: str
    model_id: str | None = None
    model_alias: list[str] = Field(default_factory=list)
    params: list[str] = Field(default_factory=list)


class ModelCatalog(BaseModel):
    models: list[ModelCatalogEntry]
    revision: int
