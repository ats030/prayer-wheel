"""rss-reader — FastAPI + vanilla JS feed reader.

``~/.env`` is loaded here rather than in app.py because config.py reads
environment variables at import time and it imports before any route does.
systemd passes the same file via EnvironmentFile; loading it here keeps a
manual ``uvicorn`` run behaving identically.
"""

from pathlib import Path

_ENV_FILE = Path.home() / ".env"
if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(_ENV_FILE)
    except ImportError:  # dotenv 未導入でも systemd 経由なら環境変数は入る
        pass
