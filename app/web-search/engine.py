"""Authenticated loopback connection to the OpenSearch indexing product."""
import ssl
from pathlib import Path

import httpx
from dotenv import dotenv_values

PRIVATE = Path.home() / ".config/web-search-opensearch"


def engine_client(admin=False):
    credentials = dotenv_values(PRIVATE / ("server.env" if admin else "reader.env"))
    password = credentials.get("OPENSEARCH_INITIAL_ADMIN_PASSWORD" if admin else "PASSWORD")
    if not password:
        raise ValueError("OpenSearch credentials are not configured")
    context = ssl.create_default_context(cafile=str(PRIVATE / "tls/server.pem"))
    return httpx.Client(base_url="https://127.0.0.1:9200", verify=context,
                        auth=("admin" if admin else "web_search_reader", password),
                        timeout=httpx.Timeout(12, connect=4), trust_env=False)


def engine_search(client, source, query, limit):
    response = client.post(f"/{source['index']}/_search", json={
        "size": limit,
        "_source": ["url", "title", "body", "fetched_at"],
        "query": {"bool": {"filter": [{"term": {"source_id": source["id"]}}],
                            "must": [{"multi_match": {"query": query,
                                      "fields": ["title^3", "body"], "operator": "and"}}]}}})
    response.raise_for_status()
    data = response.json()
    if data.get("timed_out") or data.get("_shards", {}).get("failed", 0):
        raise ValueError("OpenSearch returned an incomplete search")
    return [{"url": hit["_source"]["url"], "title": hit["_source"]["title"],
             "content": hit["_source"]["body"][:500],
             "indexed_at": hit["_source"]["fetched_at"], "engine": "opensearch"}
            for hit in data["hits"]["hits"]]
