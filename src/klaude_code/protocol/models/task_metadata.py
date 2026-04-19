from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from klaude_code.protocol.models.usage import Usage


class TaskMetadata(BaseModel):
    """Base metadata for a task execution (used by both main and sub-agents)."""

    usage: Usage | None = None
    model_name: str = ""
    provider: str | None = None
    sub_agent_name: str | None = None
    description: str | None = None
    task_duration_s: float | None = None
    turn_count: int = 0

    @staticmethod
    def merge_usage(dst: Usage, src: Usage) -> None:
        """Merge src usage into dst usage in-place."""
        dst.input_tokens += src.input_tokens
        dst.cached_tokens += src.cached_tokens
        dst.cache_write_tokens += src.cache_write_tokens
        dst.reasoning_tokens += src.reasoning_tokens
        dst.output_tokens += src.output_tokens

        if src.input_cost is not None:
            dst.input_cost = (dst.input_cost or 0.0) + src.input_cost
        if src.output_cost is not None:
            dst.output_cost = (dst.output_cost or 0.0) + src.output_cost
        if src.cache_read_cost is not None:
            dst.cache_read_cost = (dst.cache_read_cost or 0.0) + src.cache_read_cost

    @staticmethod
    def aggregate_by_model(metadata_list: list[TaskMetadata]) -> list[TaskMetadata]:
        """Aggregate multiple TaskMetadata by (model_name, provider)."""
        aggregated: dict[tuple[str, str | None], TaskMetadata] = {}

        for meta in metadata_list:
            if meta.usage is None:
                continue

            key = (meta.model_name, meta.provider)
            usage = meta.usage

            if key not in aggregated:
                aggregated[key] = TaskMetadata(
                    model_name=meta.model_name,
                    provider=meta.provider,
                    usage=Usage(currency=usage.currency),
                )

            agg = aggregated[key]
            if agg.usage is None:
                continue

            TaskMetadata.merge_usage(agg.usage, usage)

        return sorted(
            aggregated.values(),
            key=lambda item: item.usage.total_cost if item.usage and item.usage.total_cost else 0.0,
            reverse=True,
        )


def _empty_sub_agent_task_metadata() -> list[TaskMetadata]:
    return []


class TaskMetadataItem(BaseModel):
    """Aggregated metadata for a complete task, stored in conversation history."""

    main_agent: TaskMetadata = Field(default_factory=TaskMetadata)
    sub_agent_task_metadata: list[TaskMetadata] = Field(default_factory=_empty_sub_agent_task_metadata)
    is_partial: bool = False
    created_at: datetime = Field(default_factory=datetime.now)


__all__ = ["TaskMetadata", "TaskMetadataItem"]
