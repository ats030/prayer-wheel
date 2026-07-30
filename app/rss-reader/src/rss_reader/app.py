"""FastAPI app: server-rendered pages + JSON endpoints, replacing the Streamlit UI.

Why the rewrite: Streamlit re-ran the whole script on every widget interaction,
so each click re-read ~1,800 cached articles and re-rendered the page. Here the
server renders one bounded page of items (config.PAGE_SIZE), filter changes swap
a single HTML fragment, and every slow operation (feed refresh, Ollama scoring
and tagging) runs as a polled background job instead of blocking the render.

UI follows the Linear design system (see DESIGN.md / static/linear.css).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import jobs, service
from .config import PAGE_SIZE, SCORE_HIGH_THRESHOLD
from .core import feed_cache
from .core.bookmarks import Bookmark, BookmarkStore
from .core.models import FeedItem

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="rss-reader")
# 一覧は1ページ最大100件の HTML。gzip でだいたい 1/6 になる。
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

bookmark_store = BookmarkStore()

# 静的アセットのキャッシュバスター（デプロイ＝再起動なので起動時に決めれば足りる）
STATIC_VERSION = str(
    int(max((p.stat().st_mtime for p in STATIC_DIR.glob("*")), default=0))
)


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "未取得"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


templates.env.filters["dt"] = _fmt_dt
templates.env.globals.update(
    static_version=STATIC_VERSION,
    score_high=SCORE_HIGH_THRESHOLD,
    is_podcast=service.is_podcast,
    sort_orders=service.SORT_ORDERS,
    periods=service.PERIODS,
)


# --- 一覧の絞り込みパラメータ -------------------------------------------

class ListParams:
    """Query params shared by the page routes and the /partials/items fragment."""

    def __init__(
        self,
        q: str = "",
        sort: str = "",
        period: str = "すべて",
        genre: list[str] | None = None,
        feed_name: list[str] | None = None,
        offset: int = 0,
    ) -> None:
        self.q = q.strip()
        self.sort = sort if sort in service.SORT_ORDERS else "新しい順"
        self.period = period if period in service.PERIODS else "すべて"
        self.genre = genre or []
        self.feed_name = feed_name or []
        self.offset = max(0, offset)

    def as_dict(self) -> dict:
        return {
            "q": self.q,
            "sort": self.sort,
            "period": self.period,
            "genre": self.genre,
            "feed_name": self.feed_name,
        }


def _list_params(
    q: str = "",
    sort: str = "",
    period: str = "すべて",
    genre: list[str] = Query(default=[]),
    feed_name: list[str] = Query(default=[]),
    offset: int = 0,
) -> ListParams:
    return ListParams(q, sort, period, genre, feed_name, offset)


def _collect(scope: str, feed_url: str) -> tuple[list[FeedItem], datetime | None, int, list[str]]:
    """Gather the item pool for a scope. Returns (items, oldest fetch, uncached, feeds)."""
    saved = service.feed_store.load()
    if scope == "feed":
        if not feed_url:
            return [], None, 0, saved
        cached = feed_cache.load(feed_url)
        if cached is None:
            return [], None, 1, saved
        _, items, fetched_at = cached
        return items, fetched_at, 0, saved
    items, oldest, uncached = service.cached_items(saved)
    return items, oldest, uncached, saved


def _page(
    scope: str,
    feed_url: str,
    params: ListParams,
    *,
    include_llm: bool,
) -> dict:
    """Build the template context for a list of items."""
    from .core.scorer import apply_scores

    items, fetched_at, uncached, saved = _collect(scope, feed_url)
    bookmarked = {b.feed_url for b in bookmark_store.load()}
    apply_scores(items, bookmarked, include_llm=include_llm)

    filtered = service.filter_items(
        items,
        query=params.q,
        period=params.period,
        feeds=params.feed_name,
        genres=params.genre,
    )
    ordered = service.sort_items(filtered, params.sort)
    page = ordered[params.offset : params.offset + PAGE_SIZE]

    return {
        "items": page,
        "shown": min(params.offset + PAGE_SIZE, len(ordered)),
        "matched": len(ordered),
        "total": len(items),
        "next_offset": params.offset + PAGE_SIZE,
        "has_more": params.offset + PAGE_SIZE < len(ordered),
        "show_feed": scope == "new",
        "scope": scope,
        "feed_url": feed_url,
        "params": params,
        "fetched_at": fetched_at,
        "uncached": uncached,
        "saved": saved,
        "genres": sorted({i.media_type for i in items if i.media_type}),
        "feed_names": sorted({i.feed_title for i in items}),
        "include_llm": include_llm,
    }


# --- ページ -------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def feed_page(request: Request, feed: str = "", llm: int = 0):
    params = _list_params(
        q=request.query_params.get("q", ""),
        sort=request.query_params.get("sort", "新しい順"),
        period=request.query_params.get("period", "すべて"),
        genre=request.query_params.getlist("genre"),
        feed_name=request.query_params.getlist("feed_name"),
        offset=int(request.query_params.get("offset", 0) or 0),
    )
    saved = service.feed_store.load()
    active = feed if feed in saved else (saved[0] if saved else "")

    ctx = _page("feed", active, params, include_llm=bool(llm))
    meta = None
    if active:
        cached = feed_cache.load_meta(active)
        meta = cached[0] if cached else None

    bookmarks = {b.feed_url: b for b in bookmark_store.load()}
    ctx.update(
        {
            "request": request,
            "page": "feed",
            "meta": meta,
            "active": active,
            "feed_titles": service.feed_titles(saved),
            "bookmark": bookmarks.get(active),
            "thumb": service.thumbnail(meta.image_url, meta.site_url, active) if meta else "",
        }
    )
    return templates.TemplateResponse(request, "feed.html", ctx)


@app.get("/new", response_class=HTMLResponse)
def new_page(request: Request):
    params = _list_params(
        q=request.query_params.get("q", ""),
        sort=request.query_params.get("sort", "重要度順"),
        period=request.query_params.get("period", "7日"),
        genre=request.query_params.getlist("genre"),
        feed_name=request.query_params.getlist("feed_name"),
        offset=int(request.query_params.get("offset", 0) or 0),
    )
    ctx = _page("new", "", params, include_llm=False)
    ctx.update({"request": request, "page": "new"})
    return templates.TemplateResponse(request, "new.html", ctx)


@app.get("/bookmarks", response_class=HTMLResponse)
def bookmarks_page(request: Request, q: str = "", tag: list[str] = Query(default=[]),
                   genre: list[str] = Query(default=[])):
    saved = service.feed_store.load()
    bookmarks = bookmark_store.load()
    by_url = {b.feed_url: b for b in bookmarks}

    query = q.strip().lower()

    def matches(url: str) -> bool:
        bm = by_url.get(url)
        if bm is None:
            # 未保存フィードは絞り込み条件を持たないので、条件が付いた時点で外れる
            return not (tag or genre or query)
        if genre and bm.media_type not in genre:
            return False
        if tag and not any(t in bm.tags for t in tag):
            return False
        if query:
            return (
                query in bm.feed_title.lower()
                or query in bm.description.lower()
                or any(query in t.lower() for t in bm.tags)
            )
        return True

    rows = []
    for url in saved:
        if not matches(url):
            continue
        bm = by_url.get(url)
        rows.append(
            {
                "url": url,
                "bookmark": bm,
                "title": bm.feed_title if bm else service.feed_title(url),
                "thumb": service.thumbnail(bm.image_url, bm.site_url, url) if bm else "",
            }
        )

    return templates.TemplateResponse(
        request,
        "bookmarks.html",
        {
            "page": "bookmarks",
            "rows": rows,
            "saved_count": sum(1 for u in saved if u in by_url),
            "total": len(saved),
            "all_tags": sorted({t for b in bookmarks for t in b.tags}),
            "all_genres": sorted({b.media_type for b in bookmarks if b.media_type}),
            "sel_tags": tag,
            "sel_genres": genre,
            "q": q,
        },
    )


@app.get("/partials/items", response_class=HTMLResponse)
def items_fragment(request: Request, scope: str = "new", feed: str = "", llm: int = 0):
    params = _list_params(
        q=request.query_params.get("q", ""),
        sort=request.query_params.get("sort", ""),
        period=request.query_params.get("period", "すべて"),
        genre=request.query_params.getlist("genre"),
        feed_name=request.query_params.getlist("feed_name"),
        offset=int(request.query_params.get("offset", 0) or 0),
    )
    ctx = _page(scope, feed, params, include_llm=bool(llm))
    ctx["request"] = request
    return templates.TemplateResponse(request, "_items.html", ctx)


# --- JSON API -----------------------------------------------------------

class UrlBody(BaseModel):
    url: str


class TagsBody(BaseModel):
    url: str
    tags: list[str] = []


@app.get("/health")
def health():
    return {"ok": True, "feeds": len(service.feed_store.load())}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.as_dict()


@app.post("/api/feeds/detect")
def detect_feed(body: UrlBody):
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL を入力してください。")

    def run(job: jobs.Job) -> None:
        from .core.detector import detect_and_resolve

        found = detect_and_resolve(url)
        job.result = {"feeds": found}

    return {"job": jobs.start(f"detect:{url}", run, message="フィードを検索中…").as_dict()}


@app.post("/api/feeds/add")
def add_feed(body: UrlBody):
    """Register a resolved feed URL and prime its cache."""
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL が空です。")
    service.feed_store.add(url)

    def run(job: jobs.Job) -> None:
        if feed_cache.load(url) is None:
            service.refresh_feed(url)
        job.result = {"url": url, "title": service.feed_title(url)}

    return {"job": jobs.start(f"refresh:{url}", run, total=1, message="初回取得中…").as_dict()}


@app.post("/api/feeds/remove")
def remove_feed(body: UrlBody):
    service.feed_store.remove(body.url)
    feed_cache.remove(body.url)
    return {"ok": True}


@app.post("/api/feeds/refresh")
def refresh_feed(body: UrlBody):
    url = body.url

    def run(job: jobs.Job) -> None:
        service.refresh_feed(url)
        job.done = 1

    return {"job": jobs.start(f"refresh:{url}", run, total=1, message="更新中…").as_dict()}


@app.post("/api/feeds/refresh-all")
def refresh_all_feeds():
    urls = service.feed_store.load()
    if not urls:
        raise HTTPException(status_code=400, detail="フィードが登録されていません。")

    def run(job: jobs.Job) -> None:
        service.refresh_all(urls, job)

    return {"job": jobs.start("refresh_all", run, total=len(urls), message="全フィードを更新中…").as_dict()}


@app.get("/api/article")
def article(url: str):
    from .core.extractor import extract_article

    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    return {"text": extract_article(url)}


@app.post("/api/score")
def run_scoring(body: UrlBody):
    """Score one feed's cached items with Ollama; results land in the disk cache."""
    cached = feed_cache.load(body.url)
    if cached is None:
        raise HTTPException(status_code=400, detail="キャッシュがありません。先に更新してください。")
    _, items, _ = cached

    def run(job: jobs.Job) -> None:
        from .core.scorer import get_llm_score, request_llm_score

        for item in items:
            if get_llm_score(item) is None:
                request_llm_score(item)
            job.done += 1

    kind = f"score:{body.url}"
    return {"job": jobs.start(kind, run, total=len(items), message="Ollama スコアリング中…").as_dict()}


@app.get("/api/profile")
def get_profile():
    from .core.scorer import get_cached_profile

    return {"profile": get_cached_profile()}


@app.post("/api/profile/generate")
def generate_profile():
    bookmarks = bookmark_store.load()
    if not bookmarks:
        raise HTTPException(status_code=400, detail="ブックマークがありません。")

    def run(job: jobs.Job) -> None:
        from .core.scorer import generate_user_profile

        job.result = {"profile": generate_user_profile(bookmarks)}

    return {"job": jobs.start("profile", run, total=1, message="プロファイルを生成中…").as_dict()}


@app.post("/api/bookmarks/suggest-tags")
def suggest_tags(body: UrlBody):
    cached = feed_cache.load(body.url)
    if cached is None:
        raise HTTPException(status_code=400, detail="キャッシュがありません。先に更新してください。")
    meta, items, _ = cached

    def run(job: jobs.Job) -> None:
        from .core.tagger import generate_tags

        job.result = {
            "tags": generate_tags(
                meta.title,
                [i.title for i in items][:20],
                meta.description,
                meta.media_type,
                meta.feed_authors,
            )
        }

    return {"job": jobs.start(f"tags:{body.url}", run, total=1, message="タグを生成中…").as_dict()}


@app.post("/api/bookmarks/save")
def save_bookmark(body: TagsBody):
    """Create or update a bookmark, keeping the original bookmarked_at on update."""
    existing = {b.feed_url: b for b in bookmark_store.load()}.get(body.url)
    cached = feed_cache.load_meta(body.url)
    if cached is None and existing is None:
        raise HTTPException(status_code=400, detail="フィード情報がありません。先に更新してください。")

    tags = [t.strip() for t in body.tags if t.strip()]
    if cached is not None:
        meta, _ = cached
        full = feed_cache.load(body.url)
        item_titles = [i.title for i in full[1]][:20] if full else []
        bookmark = Bookmark(
            feed_url=body.url,
            feed_title=meta.title,
            description=meta.description,
            bookmarked_at=existing.bookmarked_at if existing else _now_iso(),
            tags=tags,
            site_url=meta.site_url,
            image_url=meta.image_url,
            media_type=meta.media_type,
            authors=meta.feed_authors,
            item_titles=item_titles,
        )
    else:
        # キャッシュを消したフィードでもタグだけは編集できるようにする
        bookmark = replace(existing, tags=tags)

    bookmark_store.add(bookmark)
    return {"ok": True, "tags": tags}


@app.post("/api/bookmarks/remove")
def remove_bookmark(body: UrlBody):
    bookmark_store.remove(body.url)
    return {"ok": True}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
