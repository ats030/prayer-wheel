"""Constants and on-disk paths.

Paths are absolute and anchored at RSS_READER_HOME (default ``~``) so the
service behaves the same whatever directory uvicorn is started from. The
Streamlit version used cwd-relative paths and depended on being launched from
``$HOME`` — that is why the data lives at ``~/data`` and ``~/cache``.
"""

import os
from pathlib import Path

HOME = Path(os.environ.get("RSS_READER_HOME", str(Path.home())))

HTTP_TIMEOUT = 10
FEED_CACHE_TTL = 300
ARTICLE_CACHE_TTL = 3600

DATA_DIR = HOME / "data"
DATA_FILE = DATA_DIR / "feeds.json"
BOOKMARKS_FILE = DATA_DIR / "bookmarks.json"
FEED_CACHE_DIR = DATA_DIR / "feed_cache"
CACHE_DIR = HOME / "cache"

# 一覧の1ページあたり件数。サーバー側でページングして転送量を抑える
# （キャッシュ全体は約1,800記事あり、全件を1ページに描画すると重い）。
PAGE_SIZE = int(os.environ.get("RSS_READER_PAGE_SIZE", "100"))

# 全フィード更新の並列数
REFRESH_WORKERS = int(os.environ.get("RSS_READER_REFRESH_WORKERS", "6"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

HEURISTIC_PATHS = [
    "/feed", "/feed/", "/rss", "/rss/", "/rss.xml", "/atom.xml", "/atom/",
    "/feed.xml", "/index.xml", "/feeds/posts/default", "/?format=rss",
    "/feed/rss/", "/feed/atom/", "/wp-rss2.php",
    "/arc/outboundfeeds/rss/?outputType=xml",  # Arc Publishing (Reuters, WaPo, etc.)
    "/arc/outboundfeeds/rss/",
    "/news/rss/",
    "/feeds/",
    "/api/feed/",
]

FEED_KEYWORDS_IN_HREF = ("rss", "feed", "atom", "xml")

SCORE_CACHE_TTL = 86400

# スコアの配点・閾値は settings.py（~/data/score_weights.json）に移した。
# 定数のままでは実データを見て調整できず、旧実装では重み 0.4 の鮮度成分が
# 順位をほぼ決めていることに気づけなかった。
