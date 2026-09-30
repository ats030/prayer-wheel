"""Manually refresh reviewed seed pages; no crawling or scheduled execution."""
import datetime as dt
import hashlib
import json
import re
import time
import uuid
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from dotenv import dotenv_values

from engine import PRIVATE, engine_client
from main import UA, config, enabled, fetch, in_source


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.title_mode = False
        self.title = []
        self.body = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "header", "footer"}:
            self.hidden += 1
        if tag == "title":
            self.title_mode = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "header", "footer"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.title_mode = False

    def handle_data(self, text):
        if self.title_mode:
            self.title.append(text)
        elif not self.hidden:
            self.body.append(text)


def checked(response):
    response.raise_for_status()
    return response


def provision_reader(engine):
    checked(engine.put("/_plugins/_security/api/roles/web_search_read", json={
        "cluster_permissions": [], "index_permissions": [{"index_patterns": ["websearch-*"],
        "allowed_actions": ["read"]}], "tenant_permissions": []}))
    password = dotenv_values(PRIVATE / "reader.env")["PASSWORD"]
    checked(engine.put("/_plugins/_security/api/internalusers/web_search_reader", json={
        "password": password, "opendistro_security_roles": ["web_search_read"]}))


def refresh_source(engine, web, source):
    if not enabled(source) or source["kind"] != "opensearch-engine":
        raise ValueError("Source is not approved for indexing")
    documents = []
    robots = {}
    for url in source["seed_urls"]:
        if not in_source(url, source):
            raise ValueError("Seed URL is outside the registered source")
        origin = urlsplit(url)
        root = f"{origin.scheme}://{origin.netloc}"
        if root not in robots:
            result = web.get(root + "/robots.txt")
            parser = RobotFileParser()
            if result.status_code == 404:
                parser.parse([])
            else:
                checked(result)
                if result.is_redirect:
                    raise ValueError("robots.txt redirected; review required")
                parser.parse(result.text.splitlines())
            robots[root] = parser
        if not robots[root].can_fetch(UA, url):
            raise ValueError("robots.txt prohibits seed retrieval")
        response = fetch(web, url)
        if "text/html" not in response.headers.get("content-type", ""):
            raise ValueError("Seed did not return HTML")
        page = PageText()
        page.feed(response.text)
        title = " ".join(" ".join(page.title).split())
        body = " ".join(" ".join(page.body).split())
        if not title or len(body) < 100:
            raise ValueError("Seed has insufficient page text")
        documents.append({"source_id": source["id"], "url": url, "title": title,
                          "body": body, "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
                          "terms": source["terms"]})
        time.sleep(1)
    if not documents:
        raise ValueError("Empty seed list; previous index retained")
    alias = source["index"]
    if not re.fullmatch(r"websearch-[a-z0-9-]+", alias):
        raise ValueError("Invalid index alias")
    index = alias + "-" + uuid.uuid4().hex[:12]
    checked(engine.put(f"/{index}", json={
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {"properties": {"source_id": {"type": "keyword"},
          "url": {"type": "keyword"}, "title": {"type": "text"}, "body": {"type": "text"},
          "fetched_at": {"type": "date"}, "terms": {"type": "object", "enabled": False}}}}))
    lines = []
    for document in documents:
        lines += [json.dumps({"index": {"_index": index,
                  "_id": hashlib.sha256(document["url"].encode()).hexdigest()}}), json.dumps(document)]
    result = checked(engine.post("/_bulk?refresh=true", content="\n".join(lines) + "\n",
                     headers={"Content-Type": "application/x-ndjson"})).json()
    if result.get("errors"):
        raise ValueError("Bulk indexing failed; previous alias retained")
    previous = engine.get(f"/_alias/{alias}")
    if previous.status_code == 404:
        old = {}
    else:
        old = checked(previous).json()
    actions = [{"remove": {"index": name, "alias": alias}} for name in old]
    actions.append({"add": {"index": index, "alias": alias}})
    checked(engine.post("/_aliases", json={"actions": actions}))
    return len(documents)


def main():
    with engine_client(admin=True) as engine, httpx.Client(
            timeout=20, headers={"User-Agent": UA}, follow_redirects=False) as web:
        provision_reader(engine)
        for source in config()["sources"]:
            if source["kind"] == "opensearch-engine" and enabled(source):
                count = refresh_source(engine, web, source)
                print(f"{source['id']}: indexed {count} reviewed seed pages")


if __name__ == "__main__":
    main()
