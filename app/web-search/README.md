# Shared web search

Internal JSON API on `127.0.0.1:8527`. `web-search-tailnet.service`
(`tailnet_forward.py`) forwards it, YaCy, OpenSearch Dashboards and llm-stack's
SearXNG from evo-x2's Tailnet IP to loopback for app-portal (the `/ui` search
page, the YaCy UI, Dashboards on 5601 and SearXNG on 8081); nothing listens on
the LAN, and
local callers do not depend on Tailscale. The default route is designated-site
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

Designated-site search now uses the **OpenSearch indexing product** from
https://opensearch.org/downloads/, not the unrelated OpenSearch Suggestions
protocol. Both registered sources use `kind=opensearch-engine`, a fixed index
alias, and an explicit `seed_urls` list. Initial coverage is 13 Python tutorial/
library pages and three MediaWiki API pages, not either complete site.

The official 3.9.0 image is version/digest pinned in `opensearch.yml`. It is a
single node with a 1 GiB heap, 3 GiB memory limit, two CPUs and bounded logs.
Only `127.0.0.1:9200` and Dashboards' `127.0.0.1:5601` are published; no public
port or new scheduler is installed. The API uses a dedicated read-only user scoped to `websearch-*`.
The operator's admin credential is used only for manual ingestion. Credentials
are under `~/.config/web-search-opensearch` (700 directory, 600 env files),
excluded from Git. HTTP TLS uses a privately generated certificate with
localhost/127.0.0.1 SANs; certificate and hostname verification stay enabled.
The certificate lasts 365 days: renew it and restart OpenSearch/API before
expiry. Bootstrap removes the bundled demo users, retaining only admin and
web_search_reader (plus kibanaserver once Dashboards is provisioned). The default Compose configuration also disables the known
demo admin certificate DN. Transport-layer demo TLS remains inside the
single-node container; port 9300 is not published. Replace transport TLS and
review network/user access before any multi-node or externally exposed setup.

Bootstrap (do not print the private env files or expanded Compose config):

```
.venv/bin/python app/web-search/prepare-opensearch.py
OPENSEARCH_BOOTSTRAP_ADMIN_DN='CN=kirk,OU=client,O=client,L=test,C=DE' \
  OPENSEARCH_BOOTSTRAP_CA=root-ca.pem \
  docker compose -f app/web-search/opensearch.yml up -d
# Wait for authenticated HTTPS readiness, then remove demo users once:
.venv/bin/python app/web-search/harden-opensearch.py
docker compose -f app/web-search/opensearch.yml up -d
.venv/bin/python app/web-search/ingest-opensearch.py
```

OpenSearch Dashboards 3.9.0 (digest pinned, 1.5 GiB memory limit, one CPU) runs
as the `dashboards` service in the same Compose file. It shares OpenSearch's
network namespace so it connects to `https://localhost:9200` with full
certificate and hostname verification against the private certificate. Its
server user is `kibanaserver`, because the security plugin's reserved
`kibana_server` role mapping names it; the demo password is replaced by a random
one in `dashboards.env`. People sign in as `admin` (password in `server.env`).
Settings are in `opensearch-dashboards.yml` without secrets. Setup, after the
bootstrap above (re-run `provision-dashboards.py` if `harden-opensearch.py` is
ever run again, since it removes all other users):

```
.venv/bin/python app/web-search/prepare-opensearch.py   # adds dashboards.env only
cd app/web-search && ../../.venv/bin/python provision-dashboards.py
docker compose -f opensearch.yml up -d
```

Because Dashboards joins OpenSearch's network namespace, restart them together
with `docker compose -f app/web-search/opensearch.yml up -d` (or restart
Dashboards after OpenSearch); a lone `docker restart web-search-opensearch`
leaves Dashboards without a network. The private certificate renewal above also
applies to Dashboards. Dashboards is third-party UI, so it carries no visit-log
tag (code is not injected into it).

`harden-opensearch.py` is a one-time bootstrap operation, not a refresh command.
It refuses unknown custom accounts and preserves the generated initial user
configuration in the private directory before replacement. On ordinary
restarts use only `docker compose ... up -d`, without the bootstrap DN.

Ingestion respects robots.txt, URL prefixes, reviewed source conditions, and a
one-second delay; redirects and incomplete/non-HTML pages stop the refresh.
It stores source URL, title, page text, fetched time and the terms snapshot.
Each source is rebuilt in a fresh index and its alias switches only after all
seed pages and bulk writes succeed. Deleted seeds disappear from the active
alias at the next successful refresh. Previous indices remain for rollback;
their disk usage should be monitored. No automatic refresh is configured:
edit reviewed seeds and rerun the ingestion command explicitly. Results expose
`engine=opensearch` and `indexed_at`; displayed `terms` are the current registry
conditions, not a blanket publication clearance.

Data persists in the Compose `opensearch-data` volume. Stop only this service
with `docker compose -f app/web-search/opensearch.yml stop opensearch`; do not
use `down -v` or `--remove-orphans` (the existing YaCy container is unrelated).
Rollback can point each alias at its retained previous index with `_aliases`,
or restore the prior registry/code and restart the API. Stopping the engine
makes site searches fail closed; YaCy and explicit SearXNG remain independent.

Legacy adapters are retained for compatibility but not selected by the initial
registry. `kind=opensearch` means Suggestions JSON/RSS/Atom, **not the product**.
`kind=json` supports a site-specific JSON API with `results_path` (dot-separated
object keys), `url_key`, `title_key`, and `content_key`. `kind=sphinx` searches a
static Sphinx index (`endpoint`, `base_url`) using exact English title tokens
and body-index intersections, with a one-hour in-memory cache. It is not a
Japanese semantic search or a full implementation of Sphinx stemming.
Register another site's retrieval and content-use conditions before enabling it.

## YaCy

The official image is pinned by digest in `compose.yml` (inspected version
1.942). Its UI is on loopback port 8090, reachable
from the tailnet through the forwarder above. Resource limits are 1.5 GiB memory,
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

The operator approved public-network membership on 2026-09-30. The deployed
container uses `freeworld`, including global peer search, with automatic restart
enabled. Live checks confirmed peer discovery, search through the shared API,
and page extraction through exam-trainer. Search ranking and coverage still
vary with the query and the available peers; this is not a commercial-content
clearance check.

`YACY_API_URL` defaults to `http://127.0.0.1:8090`. YaCy's GPL software licence
does not grant permission to reuse indexed page content. Web-wide discoveries
carry `review_required` content status until their conditions are checked.

## Operations and first consumer

`web-search.service` runs the API. It uses the existing Python environment,
FastAPI and httpx; no new Python dependency is introduced. Configure the app
with `WEB_SEARCH_API_URL=http://127.0.0.1:8527`; exam-trainer's service sets this
explicitly. `EXAM_TRAINER_SEARCH_SCOPE` defaults to `sites`. Other apps can
migrate independently; their current direct SearXNG connections remain usable.

The `/ui` HTML entry point includes the required visit-log tag. Deployment
checks rendered HTML with `app/deploy.sh web-search 8527`. No generated HTML
or CSP modifications are used.

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
