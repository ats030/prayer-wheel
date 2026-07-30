"""Interest profile, built from the local Obsidian index rather than feed names.

gathering-information derives its curiosity queries from the cognitive vault
(weekly synthesis + tag frequencies) instead of from what the user has already
subscribed to. Bookmarked feed titles only say "you subscribe to GIGAZINE";
the vault says what you actually think about.

The vault itself lives on the pCloud FUSE mount and is never touched here.
writing/cognitive.py already maintains a local index at
``~/.cache/writing/cognitive_index.json``; we read that, and if it is absent the
feature silently degrades to the bookmark-derived profile (the same
"vault が無ければサイレントに無効化" contract gathering-information uses).
"""

from __future__ import annotations

import collections
import json
import logging
import os
import re
from pathlib import Path

from ..config import CACHE_DIR

logger = logging.getLogger(__name__)

INDEX_PATH = Path(
    os.environ.get(
        "RSS_READER_COGNITIVE_INDEX",
        str(Path.home() / ".cache" / "writing" / "cognitive_index.json"),
    )
)

PROFILE_CACHE_KEY = "user_interest_profile"
PROFILE_SOURCE_KEY = "user_interest_profile_source"
PROFILE_TTL = 86400 * 7

# vault 内部の運用語。検索・興味の語としては意味がない。
# gathering-information の _DENY_TAGS と同趣旨。
_DENY = {
    "cognitive-stack", "daily-synthesis", "index", "tag-index", "knowledge",
    "reflection", "synthesis", "obsidian", "ars_contexta", "ars-contexta",
    "moc", "template", "templates", "inbox", "archive", "untitled",
    "architecture", "configuration", "proposal-types", "obsidian-integration",
}
# 索引化の副産物（HTMLエンティティ片・16進ID・数値のみ）を落とす
_JUNK = re.compile(r"^(?:[0-9]+|x[0-9a-f]{2,}|h[0-9a-f]{6,}|[0-9a-f]{8,})$", re.IGNORECASE)
# 長音符 ー (U+30FC) は ァ-ヶ の範囲外。含めないと #ニュース が「ニュ」で切れる。
_TAG_RE = re.compile(r"(?<![\w#])#([A-Za-z0-9ぁ-んァ-ヶー々一-龠_/-]{2,30})")
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}[-_ ]?")

_cache = None
# 索引は 1,600 件超の JSON。設定ページを開くたびに読み直さないよう mtime で持つ。
_index_memo: tuple[float, list[dict]] | None = None


def _get_cache():
    global _cache
    if _cache is None:
        import diskcache

        _cache = diskcache.Cache(str(CACHE_DIR))
    return _cache


def _load_index() -> list[dict]:
    global _index_memo
    try:
        mtime = INDEX_PATH.stat().st_mtime
    except OSError as exc:
        logger.info("cognitive index unavailable (%s); falling back to bookmarks", exc)
        return []
    if _index_memo is not None and _index_memo[0] == mtime:
        return _index_memo[1]
    try:
        data = json.loads(INDEX_PATH.read_text())
    except Exception as exc:  # noqa: BLE001 — 索引が壊れていても機能停止で済ませる
        logger.info("cognitive index unreadable (%s); falling back to bookmarks", exc)
        return []
    if not isinstance(data, list):
        return []
    records = [
        r for r in data
        if isinstance(r, dict) and "/.trash/" not in str(r.get("path", ""))
    ]
    _index_memo = (mtime, records)
    return records


_excerpt_memo: tuple[float, tuple[list[str], list[tuple[str, int]]]] | None = None


def vault_excerpt(*, notes: int = 120, top_tags: int = 20) -> tuple[list[str], list[tuple[str, int]]]:
    """Recent note titles and frequent tags. Empty when the index is missing."""
    global _excerpt_memo
    records = _load_index()
    if not records:
        return [], []
    # タグ集計は全 1,600 件の本文に正規表現をかけるので索引と同じ寿命で持つ
    mtime = _index_memo[0] if _index_memo else 0.0
    if _excerpt_memo is not None and _excerpt_memo[0] == mtime:
        return _excerpt_memo[1]

    records.sort(key=lambda r: r.get("mtime") or 0, reverse=True)
    recent = records[:notes]

    titles: list[str] = []
    for r in recent:
        title = _DATE_PREFIX.sub("", str(r.get("title", "")).strip())
        if title and title.lower() not in _DENY and not _JUNK.match(title):
            titles.append(title[:80])

    counts: collections.Counter[str] = collections.Counter()
    for r in records:
        for tag in _TAG_RE.findall(str(r.get("text", ""))):
            norm = tag.strip().lower()
            if norm in _DENY or _JUNK.match(norm) or len(norm) < 2:
                continue
            counts[norm] += 1
    # 1回しか出ないタグはノイズが多い（gathering-information と同じ足切り）
    tags = [(t, c) for t, c in counts.most_common() if c >= 2][:top_tags]
    result = (titles[:60], tags)
    _excerpt_memo = (mtime, result)
    return result


def get_cached() -> str | None:
    return _get_cache().get(PROFILE_CACHE_KEY)


def cached_source() -> str:
    return _get_cache().get(PROFILE_SOURCE_KEY) or ""


def _prompt(titles: list[str], tags: list[tuple[str, int]], bookmarks_text: str) -> str:
    blocks = []
    if tags:
        blocks.append("[頻出タグ（出現数順）]\n" + "\n".join(f"- {t} ({c})" for t, c in tags))
    if titles:
        blocks.append("[最近書いたノートの見出し]\n" + "\n".join(f"- {t}" for t in titles[:40]))
    if bookmarks_text:
        blocks.append("[購読中フィード]\n" + bookmarks_text)
    return f"""あなたはユーザの関心領域を要約します。

{chr(10).join(blocks)}

ルール:
- 3〜6項目の箇条書きで、関心のある主題・技術領域・問いの立て方を書く
- 「購読中フィード」より「頻出タグ」「ノート見出し」を優先する（前者は惰性を含む）
- 媒体名やツール名の羅列にせず、何に関心があるのかを書く
- 箇条書きのみ出力する（前置き・番号・説明は不要）

興味プロファイル:"""


def generate(bookmarks: list | None = None, model: str | None = None) -> tuple[str | None, str]:
    """Build and cache the profile. Returns (profile, source label)."""
    import os as _os

    from .llm import ask

    titles, tags = vault_excerpt()
    source = "vault" if (titles or tags) else "bookmarks"

    bookmarks_text = ""
    for bm in (bookmarks or [])[:30]:
        tag_str = ", ".join(bm.tags) if bm.tags else "（タグなし）"
        bookmarks_text += f"- {bm.feed_title} / {tag_str}\n"

    if not titles and not tags and not bookmarks_text:
        return None, "none"

    model = model or _os.environ.get("OLLAMA_PROFILE_MODEL", "").strip() or None
    text = ask(_prompt(titles, tags, bookmarks_text), model=model, num_predict=600, temperature=0.3)
    if not text:
        return None, source
    profile = text.strip()
    cache = _get_cache()
    cache.set(PROFILE_CACHE_KEY, profile, expire=PROFILE_TTL)
    cache.set(PROFILE_SOURCE_KEY, source, expire=PROFILE_TTL)
    return profile, source
