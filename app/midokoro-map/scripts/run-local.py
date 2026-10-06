#!/usr/bin/env python3
"""Load only application settings, without executing a shell env file."""
import os
from pathlib import Path
env_file = Path.home().joinpath(".env")
lines = env_file.read_text().splitlines() if env_file.exists() else []
allowed = {"JALAN_A8MAT", "TOKUSAN_AMAZON_URL", "OLLAMA_URL", "OLLAMA_MODEL"}
for prefix in ("MIDOKORO_", "OMATSURI_", "ONSEN_", "SHISEKI_", "TOKUSAN_"):
    allowed.update(line.partition("=")[0] for line in lines if line.startswith(prefix))
for line in lines:
    key, sep, value = line.partition("=")
    if sep and key in allowed:
        os.environ.setdefault(key, value)
os.execv("./app-server", ["./app-server"])
