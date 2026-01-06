"""Metadata-related protocol events."""

from __future__ import annotations

from klaude_code.protocol import model

from .base import Event, ResponseEvent


class UsageEvent(ResponseEvent):
    usage: model.Usage


class TaskMetadataEvent(Event):
    metadata: model.TaskMetadataItem
    cancelled: bool = False
