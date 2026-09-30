# Shared web search

Internal JSON API on `127.0.0.1:8527` and the host's Tailnet IPv4 (`serve.py`;
never `0.0.0.0`, so it is not on the LAN; app-portal links `/sources`). The default route is designated-site
search. YaCy is the Web-wide route; SearXNG is an explicit migration option.
There is no automatic fallback between them.

```
GET /search?q=logging&scope=sites&limit=6
GET /search?q=API&scope=sites&source=mediawiki-docs
GET /search?q=Python&scope=yacy
GET /search?q=Python&scope=searxng
GET /sources
GET /health
```

Results contain `url`, `title`, `content`, `provider`, `terms`, and
`url_prefixes`. The response contains `scope`, `searched_at`, `ok`, and
`errors`. Empty results and any provider failure make `ok=false`; the consumer
must stop collection. `/health` checks configuration readiness, not upstream
search quality. No result text is automatically cleared for publication.

## Designated sites

`sources.json` is the operator-owned registry, overridable with
`WEB_SEARCH_CONFIG`. Only enabled sources with a reviewed terms record and
explicit URL prefixes are queried. The initial sources are Python's official
English documentation and MediaWiki.org. Their reuse obligations are recorded
in `tool-license.yaml` and accompany each result.

OpenSearch is the external-site protocol, not the OpenSearch indexing product.
For an OpenSearch source, register the results URL template from its description
document using `{searchTerms}` and `{count}`. The adapter accepts Suggestions
JSON (`[query,titles,descriptions,urls]`), RSS, and Atom. HTML-only search pages
and Elasticsearch/OpenSearch product APIs are not this adapter's input.
MediaWiki's OpenSearch is a title-prefix search, so short page-title queries
work better than long natural-language examination questions.

`kind=json` supports a site-specific JSON API with `results_path` (dot-separated
object keys), `url_key`, `title_key`, and `content_key`. `kind=sphinx` searches a
static Sphinx index (`endpoint`, `base_url`) using exact English title tokens
and body-index intersections, with a one-hour in-memory cache. It is not a
Japanese semantic search or a full implementation of Sphinx stemming.
Register another site's retrieval and content-use conditions before enabling it.

## YaCy

The official image is pinned by digest in `compose.yml` (inspected version
1.942). Its UI is on port 8090 at loopback and
evo-x2's Tailnet IP `100.104.252.110` for app-portal; it is not on the LAN.
Docker does not wait for tailscaled, so if the Tailnet bind fails after boot,
run `docker start web-search-yacy`. Resource limits are 1.5 GiB memory,
768 MiB Java heap, two CPUs, and bounded logs. Persistent state is under
`/home/ats030/data/web-search-yacy`; no index is committed to Git.

The entrypoint refuses an unspecified network mode or the default admin
password. Run `.venv/bin/python app/web-search/prepare-yacy.py` once to copy the
pinned defaults, set a random admin password/hash, and store the password in
`~/.config/web-search-yacy/admin-password` with private permissions. This does
not start YaCy or join a network. The hash format is
`MD5:` plus the MD5 of `admin:<adminRealm>:<password>`; use the realm in
the actual config. Keep the password and hash out of Git and command output.

Start with `YACY_NETWORK_MODE=freeworld docker compose -f
app/web-search/compose.yml up -d` only after public-network membership is
approved. `freeworld` exchanges searches and indexes with other peers. A peer
behind NAT with only a local published port may remain a junior peer; global
coverage depends on reachable peers and is not guaranteed. `webportal` is
isolated and searches only the locally collected index. UPnP is disabled and
no public port or router mapping is created by this setup. Stop with the same
compose file's `stop` command; data is retained.

`YACY_API_URL` defaults to `http://127.0.0.1:8090`. YaCy's GPL software licence
does not grant permission to reuse indexed page content. Web-wide discoveries
carry `review_required` content status until their conditions are checked.

## Operations and first consumer

`web-search.service` runs the API. It uses the existing Python environment,
FastAPI and httpx; no new Python dependency is introduced. Configure the app
with `WEB_SEARCH_API_URL=http://127.0.0.1:8527`; exam-trainer's service sets this
explicitly. `EXAM_TRAINER_SEARCH_SCOPE` defaults to `sites`. Other apps can
migrate independently; their current direct SearXNG connections remain usable.

The service is JSON-only, so it has no HTML entry point or visit-log tag.
Deploy with `VISIT_LOG_EXEMPT_REASON='Internal JSON search API, no HTML entry
point' app/deploy.sh web-search 8527`. This reason is also recorded on the
implementation issue. No generated HTML or CSP modifications are used.

Exam-trainer persists the selected route on each job, excludes old Web-wide
cache rows from designated-site mode, and rechecks site cache metadata against
the current source registry. Manually imported pages can be used in site mode
when they match an enabled registered source. New questions retain an immutable
snapshot of URL, original fetch time and source terms, even if a page is
refetched later. Unknown Web-wide content conditions cause generated questions
to be held for human review. Conditional terms still require the publication
workflow to satisfy attribution and any other applicable obligations.

Before restarting exam-trainer, check that no jobs are running; schema changes
are additive and old queued jobs retain their original SearXNG route. To roll
back routing, remove the `WEB_SEARCH_API_URL` service override and restart
exam-trainer. Keep the additive database columns and source snapshots.

Run tests with:

```
PYTHONPATH=app/exam-trainer/src .venv/bin/pytest -q \
  app/web-search/tests/test_search.py app/exam-trainer/tests/test_exam_trainer.py
```
