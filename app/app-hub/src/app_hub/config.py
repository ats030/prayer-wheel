from __future__ import annotations

import os
from pathlib import Path


APP_HUB_DATA_DIR = Path.home() / ".local" / "share" / "app-hub"
APP_HUB_CACHE_DIR = Path.home() / ".cache" / "app-hub"


def data_dir() -> Path:
    return Path(os.environ.get("APP_HUB_DATA_DIR", APP_HUB_DATA_DIR)).expanduser()


def cache_dir() -> Path:
    return Path(os.environ.get("APP_HUB_CACHE_DIR", APP_HUB_CACHE_DIR)).expanduser()


def db_path() -> Path:
    return Path(
        os.environ.get("APP_HUB_DB_PATH", data_dir() / "hub.sqlite")
    ).expanduser()


def error_log_path() -> Path:
    return cache_dir() / "error.log"


def ensure_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    cache_dir().mkdir(parents=True, exist_ok=True)


def log_error(message: str) -> None:
    ensure_dirs()
    with error_log_path().open("a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")
