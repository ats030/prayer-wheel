"""Local metadata index for desktop app artifacts."""

from app_hub.db import (
    connect,
    init_db,
    record_artifact,
    record_event,
    record_run,
    record_source,
)

__all__ = [
    "connect",
    "init_db",
    "record_artifact",
    "record_event",
    "record_run",
    "record_source",
]
