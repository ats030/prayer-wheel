"""Settings for exam-trainer.

Loaded from ~/.env (the single source of config for the whole uv project),
mirroring writing/config.py so the two apps stay consistent.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv(Path.home() / ".env")

HOME = Path.home()


def _env(key: str, default: str) -> str:
    return os.environ.get(key, "").strip() or default


def _path(key: str, default: Path) -> Path:
    val = os.environ.get(key, "").strip()
    return Path(val).expanduser() if val else default


def _int(key: str, default: int) -> int:
    val = os.environ.get(key, "").strip()
    try:
        return int(val) if val else default
    except ValueError:
        return default


class Settings(BaseModel):
    # The bank holds every question and every answer ever given. Losing it
    # loses the learning history, which cannot be regenerated -> ~/data, which
    # backup-data.timer ships daily.
    data_dir: Path = HOME / "data" / "exam-trainer"
    # Fetched pages and embeddings can always be built again -> ~/cache.
    cache_dir: Path = HOME / "cache" / "exam-trainer"
    ollama_url: str = "http://localhost:11434"
    open_webui_url: str = ""
    open_webui_token: str = ""
    model: str = "gemma4:31b"
    # Material triage and machine-shaped work don't need the big model.
    fast_model: str = "gemma4:12b"
    embed_model: str = "nomic-embed-text"
    searxng_url: str = ""
    # How many questions a single session serves before it stops asking.
    session_size: int = 20

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bank.sqlite"


def load() -> Settings:
    return Settings(
        data_dir=_path("EXAM_TRAINER_DATA_DIR", HOME / "data" / "exam-trainer"),
        cache_dir=_path("EXAM_TRAINER_CACHE_DIR", HOME / "cache" / "exam-trainer"),
        ollama_url=_env("OLLAMA_API_URL", "http://localhost:11434"),
        open_webui_url=_env("OPEN_WEBUI_URL", ""),
        open_webui_token=_env("OPEN_WEBUI_TOKEN", ""),
        model=_env("EXAM_TRAINER_MODEL", "gemma4:31b"),
        fast_model=_env("EXAM_TRAINER_FAST_MODEL", "gemma4:12b"),
        embed_model=_env("EXAM_TRAINER_EMBED_MODEL", "nomic-embed-text"),
        searxng_url=_env("SEARXNG_API_URL", ""),
        session_size=_int("EXAM_TRAINER_SESSION_SIZE", 20),
    )


settings = load()
