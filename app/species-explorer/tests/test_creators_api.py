import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))
import creators_api

class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.status_code = 200
        self.request = httpx.Request("POST", "https://example.test")
    def json(self):
        return self.data
    def raise_for_status(self):
        return None

def test_search_product_uses_japan_all_categories_and_vended_product_url(monkeypatch):
    creators_api._TOKEN_CACHE.clear()
    calls = []
    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url == creators_api.TOKEN_URL:
            return FakeResponse({"access_token": "token-secret", "expires_in": 3600})
        return FakeResponse({"searchResult": {"items": [{
            "detailPageURL": "https://www.amazon.co.jp/dp/B000000001?tag=test-22",
            "itemInfo": {"title": {"displayValue": "身近な植物図鑑"}},
            "images": {"primary": {"medium": {"url": "https://images.example/book.jpg"}}},
        }]}})
    monkeypatch.setattr(creators_api.httpx, "post", fake_post)
    product = creators_api.search_product("タンポポ", "credential", "secret", "test-22")
    assert product["title"] == "身近な植物図鑑"
    assert product["url"].startswith("https://www.amazon.co.jp/dp/")
    request = calls[1][1]
    assert request["headers"]["Authorization"] == "Bearer token-secret"
    assert request["headers"]["x-marketplace"] == "www.amazon.co.jp"
    assert request["json"]["searchIndex"] == "All"
    assert request["json"]["itemCount"] == 1
    assert request["json"]["keywords"] == "タンポポ"

def test_access_token_is_reused_until_expiry(monkeypatch):
    creators_api._TOKEN_CACHE.clear()
    token_calls = 0
    def fake_post(url, **kwargs):
        nonlocal token_calls
        if url == creators_api.TOKEN_URL:
            token_calls += 1
            return FakeResponse({"access_token": "cached-token", "expires_in": 3600})
        return FakeResponse({"searchResult": {"items": []}})
    monkeypatch.setattr(creators_api.httpx, "post", fake_post)
    creators_api.search_product("鳥", "credential", "secret", "test-22")
    creators_api.search_product("花", "credential", "secret", "test-22")
    assert token_calls == 1

def test_non_amazon_product_url_is_rejected(monkeypatch):
    creators_api._TOKEN_CACHE.clear()
    monkeypatch.setattr(creators_api, "_token", lambda *args: "token")
    monkeypatch.setattr(creators_api.httpx, "post", lambda *args, **kwargs: FakeResponse({
        "searchResult": {"items": [{"detailPageURL": "https://evil.example/product", "itemInfo": {"title": {"displayValue": "fake"}}}]}
    }))
    assert creators_api.search_product("花", "id", "secret", "tag") is None
