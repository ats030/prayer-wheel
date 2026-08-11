import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import webdav_relay


@pytest.mark.parametrize("url,expected", [
    ("http://example.com/f.json", "https://"),          # 平文で認証情報を流さない
    ("https://127.0.0.1/f.json", "内部ネットワーク"),
    ("https://localhost/f.json", "内部ネットワーク"),
    ("https://169.254.169.254/latest/meta-data", "内部ネットワーク"),  # クラウドのメタデータ
    ("https://192.168.0.1/f.json", "内部ネットワーク"),
    ("", "https://"),
])
def test_relay_refuses_dangerous_targets(url, expected):
    """中継は SSRF の入口になる。ホスト名ではなく解決先のアドレスで判断する。"""
    with pytest.raises(webdav_relay.RelayError) as error:
        webdav_relay.validate(url)
    assert expected in str(error.value)


def test_relay_allows_a_normal_https_host():
    assert webdav_relay.validate("https://webdav.pcloud.com/note.json").startswith("https://")


def test_relay_does_not_follow_redirects():
    """検証を通った先から内部へ飛ばされないようにする。"""
    with webdav_relay._client() as client:
        assert client.follow_redirects is False


def test_relay_passes_credentials_and_reports_failures(monkeypatch):
    seen = {}

    class FakeClient:
        follow_redirects = False
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def put(self, url, content=None, auth=None, headers=None):
            seen.update(url=url, auth=auth, size=len(content))
            return httpx.Response(201)
        def get(self, url, auth=None):
            seen.update(url=url, auth=auth)
            return httpx.Response(seen.pop("status", 200), content=b'{"ok":1}')

    monkeypatch.setattr(webdav_relay, "_reject_internal", lambda host: None)
    monkeypatch.setattr(webdav_relay, "_client", lambda: FakeClient())

    webdav_relay.put("https://dav.example/notes/", "user", "pass", b"{}")
    assert seen["auth"] == ("user", "pass")
    assert seen["url"] == "https://dav.example/notes/" + webdav_relay.FILE_NAME

    assert webdav_relay.get("https://dav.example/notes/", "user", "pass") == b'{"ok":1}'

    seen["status"] = 401
    with pytest.raises(webdav_relay.RelayError) as error:
        webdav_relay.get("https://dav.example/notes/", "user", "bad")
    assert "パスワード" in str(error.value)


def test_relay_caps_the_size():
    with pytest.raises(webdav_relay.RelayError):
        webdav_relay.put("https://dav.example/notes/", "u", "p", b"x" * (webdav_relay.MAX_BYTES + 1))


@pytest.mark.parametrize("folder,expected", [
    ("https://dav.example/notes/", "https://dav.example/notes/ikimono-note.json"),
    ("https://dav.example/notes", "https://dav.example/notes/ikimono-note.json"),
    ("https://dav.example/", "https://dav.example/ikimono-note.json"),
    # すでにファイルまで指定されていれば二重に足さない
    ("https://dav.example/notes/ikimono-note.json", "https://dav.example/notes/ikimono-note.json"),
])
def test_folder_gets_the_app_owned_file_name(folder, expected, monkeypatch):
    """利用者はフォルダだけ決める。名前を任意にすると別用途のファイルを上書きしうる。"""
    monkeypatch.setattr(webdav_relay, "_reject_internal", lambda host: None)
    assert webdav_relay.file_url(folder) == expected
