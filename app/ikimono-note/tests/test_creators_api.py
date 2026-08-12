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

def test_search_products_uses_japan_all_categories_and_vended_product_urls(monkeypatch):
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
    products = creators_api.search_products("タンポポ", "credential", "secret", "test-22")
    assert products[0]["title"] == "身近な植物図鑑"
    assert products[0]["url"].startswith("https://www.amazon.co.jp/dp/")
    request = calls[1][1]
    assert request["headers"]["Authorization"] == "Bearer token-secret"
    assert request["headers"]["x-marketplace"] == "www.amazon.co.jp"
    assert request["json"]["searchIndex"] == "All"
    assert request["json"]["itemCount"] == 4
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
    creators_api.search_products("鳥", "credential", "secret", "test-22")
    creators_api.search_products("花", "credential", "secret", "test-22")
    assert token_calls == 1

def test_non_amazon_product_url_is_rejected(monkeypatch):
    creators_api._TOKEN_CACHE.clear()
    monkeypatch.setattr(creators_api, "_token", lambda *args: "token")
    monkeypatch.setattr(creators_api.httpx, "post", lambda *args, **kwargs: FakeResponse({
        "searchResult": {"items": [{"detailPageURL": "https://evil.example/product", "itemInfo": {"title": {"displayValue": "fake"}}}]}
    }))
    assert creators_api.search_products("花", "id", "secret", "tag") == []


class RefusedResponse:
    """Amazon が断ったときの応答。raise_for_status が HTTPStatusError を投げる。"""

    def __init__(self, status_code, data):
        self.status_code = status_code
        self.data = data
        self.text = str(data)
        self.request = httpx.Request("POST", "https://example.test")

    def json(self):
        return self.data

    def raise_for_status(self):
        raise httpx.HTTPStatusError("refused", request=self.request, response=self)


def _refuse(monkeypatch, status_code, body):
    creators_api._TOKEN_CACHE.clear()
    def fake_post(url, **kwargs):
        if url == creators_api.TOKEN_URL:
            return FakeResponse({"access_token": "token-secret", "expires_in": 3600})
        return RefusedResponse(status_code, body)
    monkeypatch.setattr(creators_api.httpx, "post", fake_post)


def test_amazon_refusal_reaches_the_operator_not_the_visitor(monkeypatch, capsys):
    """断られた理由は journal へ。画面の言葉は変えない。

    実際に AssociateNotEligible (適格販売が足りない) で商品APIが止まっていたが、
    サーバーは何も残さず、画面は検索リンクへ静かに戻るだけだった。原因を掴むのに
    手で API を叩くしかなく、設定画面は「認証情報を登録済み」と出したままだった。
    """
    _refuse(monkeypatch, 403, {"message": "Your account does not currently meet the eligibility requirements.",
                               "reason": "AssociateNotEligible", "type": "AccessDeniedException"})
    try:
        creators_api.search_products("タンポポ", "credential", "secret", "test-22")
        raise AssertionError("断られたのに例外が出ていない")
    except creators_api.CreatorsAPIError as error:
        # 利用者にはAmazon側の事情を見せない (公開版の訪問者には何も設定できない)
        assert str(error) == "Amazonの商品情報を取得できませんでした"
        assert "AssociateNotEligible" not in str(error)
    journal = capsys.readouterr().out
    assert "403" in journal
    assert "AssociateNotEligible" in journal
    assert "適格販売" in journal  # 運営者がとれる手まで書く


def test_unknown_refusal_still_records_status_and_message(monkeypatch, capsys):
    """理由に見覚えがなくても、状態と本文は残す。無言で消さないことが要件。"""
    _refuse(monkeypatch, 429, {"message": "slow down", "type": "TooManyRequests"})
    try:
        creators_api.search_products("タンポポ", "credential", "secret", "test-22")
    except creators_api.CreatorsAPIError:
        pass
    journal = capsys.readouterr().out
    assert "429" in journal and "slow down" in journal


def test_unreachable_amazon_is_also_recorded(monkeypatch, capsys):
    """届かなかった場合も journal に出す。無音だと設定ミスと区別が付かない。"""
    creators_api._TOKEN_CACHE.clear()
    def fake_post(url, **kwargs):
        if url == creators_api.TOKEN_URL:
            return FakeResponse({"access_token": "token-secret", "expires_in": 3600})
        raise httpx.ConnectError("no route to host")
    monkeypatch.setattr(creators_api.httpx, "post", fake_post)
    try:
        creators_api.search_products("タンポポ", "credential", "secret", "test-22")
    except creators_api.CreatorsAPIError:
        pass
    assert "届きませんでした" in capsys.readouterr().out
