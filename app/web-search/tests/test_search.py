import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location("shared_search", Path(__file__).parents[1] / "main.py")
search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search)


@pytest.fixture
def source():
    return {"id": "docs", "kind": "opensearch", "enabled": True,
            "endpoint": "https://docs.example.org/search?q={searchTerms}&count={count}",
            "url_prefixes": ["https://docs.example.org/manual/"],
            "terms": {"status": "conditional", "checked_at": "2026-09-30",
                      "links": ["https://docs.example.org/license"], "conditions": "Attribute"}}


def response(payload, kind="application/json"):
    return httpx.Response(200, json=payload, headers={"content-type": kind},
                          request=httpx.Request("GET", "https://docs.example.org/search"))


def test_opensearch_json_and_rss():
    hits = search.parse_opensearch(response(["q", ["Title"], ["Text"], ["https://example.org/doc"]]))
    assert hits == [{"title": "Title", "url": "https://example.org/doc", "content": "Text"}]
    rss = httpx.Response(200, text='<rss><channel><item><title>Doc</title><link>https://example.org/doc</link></item></channel></rss>')
    assert search.parse_opensearch(rss)[0]["url"] == "https://example.org/doc"
    atom = httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Doc</title><link href="https://example.org/doc"/></entry></feed>')
    assert search.parse_opensearch(atom)[0]["url"] == "https://example.org/doc"


def test_opensearch_rejects_html_and_entities():
    with pytest.raises(ValueError):
        search.parse_opensearch(httpx.Response(200, text="<html><body>Login</body></html>"))
    with pytest.raises(ValueError):
        search.parse_opensearch(httpx.Response(200, text='<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss/>'))


@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://[::1]/x", "http://localhost/x",
                                  "http://192.168.0.2/x", "https://user:pw@example.org/doc", "file:///etc/passwd"])
def test_private_and_non_http_results_rejected(url):
    assert not search.public_url(url)


def test_source_domain_and_path_are_enforced(source):
    assert search.in_source("https://docs.example.org/manual/a.html", source)
    assert not search.in_source("https://docs.example.org.evil.org/manual/a.html", source)
    assert not search.in_source("https://docs.example.org/elsewhere/a.html", source)
    assert not search.in_source("http://docs.example.org/manual/a.html", source)


def test_unreviewed_source_disabled(source):
    assert search.enabled(source)
    source["terms"]["status"] = "review_required"
    assert not search.enabled(source)


def test_site_results_carry_terms_and_escape_query(monkeypatch, source):
    urls = []
    def get(client, url, params=None):
        urls.append(url)
        return response(["q", ["Good", "Bad"], ["", ""],
                         ["https://docs.example.org/manual/a", "https://evil.org/a"]])
    monkeypatch.setattr(search, "fetch", get)
    hits, error = search.site_search(source, "a&b #", 6)
    assert not error
    assert len(hits) == 1
    assert hits[0]["terms"] == source["terms"]
    assert "a%26b%20%23" in urls[0]


def test_site_failure_does_not_call_general_search(monkeypatch, source):
    monkeypatch.setattr(search, "config", lambda: {"sources": [source]})
    monkeypatch.setattr(search, "site_search", lambda *a: ([], "docs: timeout"))
    monkeypatch.setattr(search, "general_search", lambda *a: pytest.fail("implicit general fallback"))
    result = TestClient(search.app).get("/search", params={"q": "python"}).json()
    assert result["scope"] == "sites" and not result["ok"]
    assert result["errors"] == ["docs: timeout"]


def test_partial_failure_is_not_success(monkeypatch, source):
    other = {**source, "id": "other"}
    monkeypatch.setattr(search, "config", lambda: {"sources": [source, other]})
    monkeypatch.setattr(search, "site_search", lambda s, *a:
                        ([{"url": "https://docs.example.org/manual/a"}], "") if s["id"] == "docs" else ([], "other: timeout"))
    result = TestClient(search.app).get("/search", params={"q": "python"}).json()
    assert result["results"] and not result["ok"]


def test_round_robin_and_deduplication(monkeypatch, source):
    monkeypatch.setattr(search, "config", lambda: {"sources": [source, {**source, "id": "other"}]})
    monkeypatch.setattr(search, "site_search", lambda s, *a: (
        [{"url": f"https://example.org/{s['id']}/{i}"} for i in range(3)], ""))
    result = TestClient(search.app).get("/search", params={"q": "python", "limit": 3}).json()
    assert [row["url"] for row in result["results"]] == [
        "https://example.org/docs/0", "https://example.org/other/0", "https://example.org/docs/1"]


def test_yacy_global_request_and_normalization(monkeypatch):
    calls = []
    def get(client, url, params=None):
        calls.append((url, params))
        return response({"channels": [{"items": [{"link": "https://example.org/a?x=1&amp;y=2", "title": "A &amp; B", "description": "Desc"}]}]})
    monkeypatch.setattr(search, "fetch", get)
    terms = {"status": "review_required"}
    hits, errors = search.general_search("yacy", "python", 6, {"general_terms": {"yacy": terms}})
    assert not errors and hits[0]["provider"] == "yacy"
    assert hits[0]["terms"] == terms
    assert hits[0]["url"] == "https://example.org/a?x=1&y=2"
    assert hits[0]["title"] == "A & B"
    assert calls[0][1]["resource"] == "global"
    assert calls[0][0].endswith("/yacysearch.json")


def test_source_selection_and_validation(monkeypatch, source):
    monkeypatch.setattr(search, "config", lambda: {"sources": [source]})
    client = TestClient(search.app)
    assert client.get("/search", params={"q": "q", "source": "unknown"}).status_code == 503
    assert client.get("/search", params={"q": "q", "scope": "any"}).status_code == 422
    assert client.get("/search", params={"q": "q", "scope": "yacy", "source": "docs"}).status_code == 422


def test_sphinx_static_index_search(monkeypatch, source):
    index = {"titles": ["Python logging", "Socket"], "docnames": ["library/logging", "library/socket"],
             "terms": {"logging": 0, "socket": 1}}
    import json
    source.update(kind="sphinx", endpoint="https://docs.example.org/index.js", base_url="https://docs.example.org/manual/")
    search._index_cache.clear()
    monkeypatch.setattr(search, "fetch", lambda *a: httpx.Response(200, text="Search.setIndex(" + json.dumps(index) + ")"))
    hits, error = search.site_search(source, "logging", 6)
    assert not error and hits[0]["url"] == "https://docs.example.org/manual/library/logging.html"


def test_yacy_preparation_keeps_password_private_and_network_isolated(monkeypatch, tmp_path):
    import hashlib
    spec = importlib.util.spec_from_file_location("prepare_yacy", Path(__file__).parents[1] / "prepare-yacy.py")
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    monkeypatch.setattr(prepare, "DATA", tmp_path / "data")
    monkeypatch.setattr(prepare, "PRIVATE", tmp_path / "private")
    monkeypatch.setattr(prepare.subprocess, "check_output", lambda *a, **kw:
                        "adminRealm=Test realm\nadminAccountBase64MD5=default\nnetwork.unit.definition=freeworld\n")
    prepare.prepare()
    password = (prepare.PRIVATE / "admin-password").read_text().strip()
    config = (prepare.DATA / "yacy.conf").read_text()
    assert len(password) >= 32 and password not in config
    assert hashlib.md5(f"admin:Test realm:{password}".encode()).hexdigest() in config
    assert "network.unit.definition=defaults/yacy.network.webportal.unit" in config
    assert (prepare.PRIVATE / "admin-password").stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemExit):
        prepare.prepare()


def test_ui_renders_escaped_results(monkeypatch):
    monkeypatch.setattr(search, "config", lambda: {"sources": [{"id": "docs", "enabled": True}]})
    monkeypatch.setattr(search, "enabled", lambda s: True)
    monkeypatch.setattr(search, "search", lambda q, scope, limit, source: {
        "results": [{"url": "https://docs.example.org/manual/a", "title": "<code>argparse</code> &lt;x&gt;",
                     "content": "", "provider": "docs", "terms": {"license": "MIT"}}], "errors": []})
    page = TestClient(search.app).get("/ui", params={"q": "<b>"}).text
    assert 'data-site="web-search"' in page
    assert "argparse &lt;x&gt;" in page and "<code>" not in page
    assert ">すべて</option>" in page
    assert 'value="&lt;b&gt;"' in page


def test_engine_query_and_result_provenance(monkeypatch, source):
    from engine import engine_search
    calls = []
    def handle(request):
        import json
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"hits": {"hits": [{"_source": {
            "url": "https://docs.example.org/manual/a", "title": "Doc", "body": "Python text",
            "fetched_at": "2026-09-30T00:00:00Z"}}]}, "_shards": {"failed": 0}})
    source.update(kind="opensearch-engine", index="websearch-docs")
    def client():
        return httpx.Client(base_url="https://localhost:9200", transport=httpx.MockTransport(handle))
    monkeypatch.setattr(search, "engine_client", client)
    hits, error = search.site_search(source, "Python", 3)
    assert not error and hits[0]["engine"] == "opensearch"
    assert hits[0]["indexed_at"] == "2026-09-30T00:00:00Z"
    assert hits[0]["terms"] == source["terms"]
    assert calls[0][0] == "/websearch-docs/_search"
    assert calls[0][1]["query"]["bool"]["filter"] == [{"term": {"source_id": "docs"}}]


@pytest.mark.parametrize("payload", [{"timed_out": True}, {"_shards": {"failed": 1}}])
def test_engine_partial_results_fail_closed(monkeypatch, source, payload):
    source.update(kind="opensearch-engine", index="websearch-docs")
    monkeypatch.setattr(search, "engine_client", lambda: httpx.Client(base_url="https://localhost:9200",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))))
    hits, error = search.site_search(source, "Python", 3)
    assert not hits and error


def test_ingestion_switches_alias_only_after_success(monkeypatch, source):
    spec = importlib.util.spec_from_file_location("ingest_engine", Path(__file__).parents[1] / "ingest-opensearch.py")
    ingest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ingest)
    monkeypatch.setattr(ingest.time, "sleep", lambda *a: None)
    source.update(kind="opensearch-engine", index="websearch-docs",
                  seed_urls=["https://docs.example.org/manual/a"])
    calls = []
    fail_bulk = [False]
    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/_bulk":
            return httpx.Response(200, json={"errors": fail_bulk[0]})
        if request.url.path == "/_alias/websearch-docs":
            return httpx.Response(404)
        return httpx.Response(200, json={"acknowledged": True})
    def page(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, text="<html><title>Doc</title><body>" + "Python programming " * 30 + "</body></html>",
                              headers={"content-type": "text/html"})
    with httpx.Client(base_url="https://localhost:9200", transport=httpx.MockTransport(handle)) as engine, \
            httpx.Client(transport=httpx.MockTransport(page)) as web:
        assert ingest.refresh_source(engine, web, source) == 1
        assert calls[-1] == "/_aliases"
        calls.clear()
        fail_bulk[0] = True
        with pytest.raises(ValueError, match="Bulk"):
            ingest.refresh_source(engine, web, source)
        assert "/_aliases" not in calls
        calls.clear()
        source["seed_urls"] = ["http://127.0.0.1/private"]
        with pytest.raises(ValueError, match="outside"):
            ingest.refresh_source(engine, web, source)
        assert not calls


def test_hardening_refuses_custom_accounts(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("harden_engine", Path(__file__).parents[1] / "harden-opensearch.py")
    harden = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harden)
    monkeypatch.setattr(harden, "PRIVATE", tmp_path)
    monkeypatch.setattr(harden, "engine_client", lambda **kw: httpx.Client(base_url="https://localhost:9200",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"admin": {}, "custom": {}}))))
    monkeypatch.setattr(harden.subprocess, "check_output", lambda *a, **kw: pytest.fail("must preserve custom users"))
    with pytest.raises(ValueError, match="Unknown custom"):
        harden.harden()
    assert not list(tmp_path.iterdir())


def test_reader_connection_keeps_tls_and_has_no_admin_secret(monkeypatch, tmp_path):
    import engine
    import ssl
    (tmp_path / "reader.env").write_text("PASSWORD=test-reader\n")
    monkeypatch.setattr(engine, "PRIVATE", tmp_path)
    context = ssl.create_default_context()
    paths = []
    monkeypatch.setattr(engine.ssl, "create_default_context", lambda **kw: (paths.append(kw) or context))
    arguments = []
    monkeypatch.setattr(engine.httpx, "Client", lambda **kw: arguments.append(kw))
    engine.engine_client()
    assert arguments[0]["auth"] == ("web_search_reader", "test-reader")
    assert arguments[0]["base_url"] == "https://127.0.0.1:9200"
    assert arguments[0]["verify"].check_hostname
    assert arguments[0]["verify"].verify_mode == ssl.CERT_REQUIRED
    assert not arguments[0]["trust_env"]


def test_dashboards_server_user_uses_private_password_and_reserved_mapping(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("provision_dashboards",
                                                  Path(__file__).parents[1] / "provision-dashboards.py")
    provision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provision)
    (tmp_path / "dashboards.env").write_text("OPENSEARCH_DASHBOARDS_SERVER_PASSWORD=test-dash\n")
    monkeypatch.setattr(provision, "PRIVATE", tmp_path)
    requests = []

    def reply(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"kibana_server": {"users": ["kibanaserver"]}})
        return httpx.Response(200, json={"status": "OK"})
    with httpx.Client(base_url="https://localhost:9200", transport=httpx.MockTransport(reply)) as engine:
        provision.provision_dashboards(engine)
    assert requests[0].url.path == "/_plugins/_security/api/internalusers/kibanaserver"
    assert json.loads(requests[0].content) == {"password": "test-dash"}
    (tmp_path / "dashboards.env").write_text("")
    with pytest.raises(ValueError, match="not configured"):
        provision.provision_dashboards(None)


def test_dashboards_is_loopback_only_and_forwarded_to_tailnet():
    import tailnet_forward
    compose = (Path(__file__).parents[1] / "opensearch.yml").read_text()
    config = (Path(__file__).parents[1] / "opensearch-dashboards.yml").read_text()
    assert '"127.0.0.1:5601:5601"' in compose and 'network_mode: "service:opensearch"' in compose
    assert "verificationMode: full" in config and "Aa1!" not in config
    assert 5601 in tailnet_forward.PORTS
