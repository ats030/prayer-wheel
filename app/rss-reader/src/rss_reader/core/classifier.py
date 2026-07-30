import re


# テックニュース系ドメイン
_TECH_NEWS_DOMAINS = {
    "gigazine.net", "techcrunch.com", "wired.com", "wired.jp",
    "itmedia.co.jp", "zdnet.com", "theverge.com", "engadget.com",
    "gizmodo.com", "arstechnica.com", "thenextweb.com", "venturebeat.com",
    "9to5mac.com", "9to5google.com", "macrumors.com", "slashdot.org",
    "news.ycombinator.com", "ascii.jp", "mycom.jp", "mynavi.jp",
}

# 一般ニュース系ドメイン
_NEWS_DOMAINS = {
    "nhk.or.jp", "nytimes.com", "bbc.com", "bbc.co.uk", "reuters.com",
    "apnews.com", "cnn.com", "theguardian.com", "nikkei.com", "nikkei.co.jp",
    "mainichi.jp", "yomiuri.co.jp", "asahi.com", "sankei.com",
    "japantimes.co.jp", "bloomberg.com", "wsj.com", "ft.com",
    "tokyoreporter.com", "jiji.com", "kyodo.co.jp",
}

# テックブログ系ドメイン・プラットフォーム
_TECH_BLOG_DOMAINS = {
    "zenn.dev", "qiita.com", "dev.to", "medium.com",
    "hatenablog.com", "hatena.ne.jp",
}
_TECH_BLOG_TITLE_KW = (
    "blog", "zenn", "qiita", "ブログ", "tech", "engineering",
    "developer", "開発", "エンジニア",
)

# 論文・研究系ドメイン
_RESEARCH_DOMAINS = {
    "arxiv.org", "doi.org", "pubmed.ncbi.nlm.nih.gov", "semanticscholar.org",
    "nature.com", "science.org", "scholar.google.com", "researchgate.net",
    "acm.org", "ieee.org", "springer.com", "mdpi.com", "sciencedirect.com",
}

# リリース・更新履歴の URL パターン
_RELEASE_URL_RE = re.compile(
    r'/(releases?|changelog|release[-_]notes?|updates?|whatsnew)',
    re.IGNORECASE,
)
# バージョン番号パターン（タイトル先頭寄り）
_VERSION_RE = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?(?:[a-z]\d*)?\b', re.IGNORECASE)
_RELEASE_TITLE_KW = (
    "changelog", "release notes", "リリースノート", "更新情報", "更新履歴",
    "what's new", "リリース", "アップデート",
)


def _domain(url: str) -> str:
    m = re.search(r'https?://([^/]+)', url)
    if not m:
        return ""
    host = m.group(1).lower().lstrip("www.")
    # サブドメインを除いた最後の2〜3ラベルを返す
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def classify_media_type(feed, entries, url: str = "") -> str:
    # 1. ポッドキャスト / 動画（enclosure 最優先）
    for entry in entries:
        for enc in entry.get("enclosures", []):
            t = enc.get("type", "")
            if "audio" in t:
                return "ポッドキャスト"
            if "video" in t:
                return "動画"

    site_url = feed.get("link", "")
    feed_title = feed.get("title", "")
    feed_title_lower = feed_title.lower()

    if "youtube.com/feeds" in url or "youtube.com/feeds" in site_url:
        return "動画"

    # ドメイン判定用
    dom = _domain(url) or _domain(site_url)

    # 2. リリース・更新履歴
    if (
        _RELEASE_URL_RE.search(url)
        or any(kw in feed_title_lower for kw in _RELEASE_TITLE_KW)
        or (entries and _VERSION_RE.search(entries[0].get("title", "")))
    ):
        # GitHub Releases などはエントリタイトルがバージョン番号になる
        version_titles = sum(
            1 for e in entries[:5] if _VERSION_RE.search(e.get("title", ""))
        )
        if version_titles >= 2 or _RELEASE_URL_RE.search(url):
            return "リリース・更新履歴"

    # 3. 論文・研究
    if dom in _RESEARCH_DOMAINS:
        return "論文・研究"

    # 4. テックニュース
    if dom in _TECH_NEWS_DOMAINS:
        return "テックニュース"

    # 5. 一般ニュース
    if dom in _NEWS_DOMAINS:
        return "一般ニュース"

    # 6. テックブログ / 個人ブログ（著者数＋タイトル・ドメインで判定）
    authors = _collect_entry_authors(entries)

    if dom in _TECH_BLOG_DOMAINS or any(kw in feed_title_lower for kw in _TECH_BLOG_TITLE_KW):
        if len(authors) <= 2:
            return "テックブログ"

    # 7. タイトルキーワードによるニュース判定（既存ロジック）
    if any(k in feed_title for k in ("ニュース", "News", "news", "速報")):
        return "一般ニュース"

    # 8. 著者数による推定
    if len(authors) >= 3:
        return "一般ニュース"
    if len(authors) == 1:
        return "個人ブログ"

    return "その他"


def extract_feed_authors(feed, entries) -> list[str]:
    feed_author = (
        feed.get("author_detail", {}).get("name")
        or feed.get("author")
        or feed.get("itunes_author", "")
    )
    feed_author = _clean(feed_author)

    entry_authors = _collect_entry_authors(entries)

    result: list[str] = []
    if feed_author:
        result.append(feed_author)
    for a in entry_authors:
        if a not in result:
            result.append(a)
        if len(result) >= 5:
            break
    return result


def extract_item_author(entry) -> str | None:
    raw = (
        entry.get("author_detail", {}).get("name")
        or entry.get("author")
    )
    return _clean(raw) or None


def _collect_entry_authors(entries) -> list[str]:
    seen: list[str] = []
    for entry in entries:
        name = _clean(
            entry.get("author_detail", {}).get("name") or entry.get("author")
        )
        if name and name not in seen:
            seen.append(name)
    return seen


def _clean(s) -> str:
    if not s:
        return ""
    s = str(s).strip()
    s = re.sub(r"\s*\(.*?\)\s*$", "", s)
    s = re.sub(r"\s*<[^>]+>\s*$", "", s)
    return s.strip()
