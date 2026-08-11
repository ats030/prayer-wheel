"""利用者のクラウドストレージ (WebDAV) への中継。

ブラウザから外部ストレージへ直接つなぐことは、CORS と CSP の両方で塞がっている。
そのためサーバーが中継する。認証情報は毎回のリクエストで受け取り、保存も記録もしない。

中継は SSRF の入口になる。任意のURLへ代理でつなぐ機能を、そのまま外へ出してはいけない。
接続先は https に限り、名前解決した先が内部アドレスなら拒否する。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import unquote, urljoin, urlparse
from xml.etree import ElementTree

import httpx

MAX_BYTES = 25 * 1024 * 1024
TIMEOUT = 60
# 利用者にはフォルダだけ決めてもらい、ファイル名はアプリが持つ。
# 名前を任意にすると、うっかり別の用途のファイルを上書きしうる。
FILE_NAME = "ikimono-note.json"


class RelayError(RuntimeError):
    pass


def _reject_internal(host: str) -> None:
    """名前解決の結果が内部を指していたら止める。ホスト名だけの検査では抜けられる。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise RelayError("接続先の名前を解決できませんでした") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast or address.is_unspecified):
            raise RelayError("この接続先は指定できません（内部ネットワーク）")


def file_url(folder: str) -> str:
    """フォルダのURLに、アプリが決めたファイル名を足す。"""
    base = validate(folder)
    if base.endswith("/" + FILE_NAME):
        return base                      # すでにファイルまで指定されている場合はそのまま
    return base.rstrip("/") + "/" + FILE_NAME


def validate(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https":
        raise RelayError("接続先は https:// で指定してください（認証情報が平文で流れないため）")
    if not parsed.hostname:
        raise RelayError("接続先を確認してください")
    # ポートは絞らない。守るべきは「内部へ行かせない」ことで、外部の任意ポートを
    # 塞ぐと自前の Nextcloud のような正当な接続先を弾いてしまう
    _reject_internal(parsed.hostname)
    return parsed.geturl()


def _client() -> httpx.Client:
    # リダイレクトを追うと、検証を通った先から内部へ飛ばされうる
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False)


def put(folder: str, user: str, password: str, body: bytes) -> None:
    if len(body) > MAX_BYTES:
        raise RelayError("記録が大きすぎます")
    target = file_url(folder)
    try:
        with _client() as client:
            response = client.put(target, content=body, auth=(user, password),
                                  headers={"Content-Type": "application/json"})
    except httpx.HTTPError as exc:
        raise RelayError("接続先へ届きませんでした") from exc
    if response.status_code in (401, 403):
        raise RelayError("接続先の利用者名またはパスワードを確認してください")
    if response.status_code >= 400:
        raise RelayError(f"接続先が保存を拒否しました（{response.status_code}）")


def get(folder: str, user: str, password: str) -> bytes:
    target = file_url(folder)
    try:
        with _client() as client:
            response = client.get(target, auth=(user, password))
    except httpx.HTTPError as exc:
        raise RelayError("接続先へ届きませんでした") from exc
    if response.status_code in (401, 403):
        raise RelayError("接続先の利用者名またはパスワードを確認してください")
    if response.status_code == 404:
        raise RelayError("接続先にファイルがありません")
    if response.status_code >= 400:
        raise RelayError(f"接続先から読み取れませんでした（{response.status_code}）")
    if len(response.content) > MAX_BYTES:
        raise RelayError("ファイルが大きすぎます")
    return response.content


PROPFIND_BODY = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:displayname/></d:prop></d:propfind>"""


def list_folders(folder: str, user: str, password: str) -> list[dict[str, str]]:
    """1階層ぶんのフォルダを返す。URLを手で組み立てずに選べるようにするため。"""
    target = validate(folder)
    if not target.endswith("/"):
        target += "/"
    try:
        with _client() as client:
            response = client.request("PROPFIND", target, auth=(user, password),
                                      headers={"Depth": "1", "Content-Type": "application/xml"},
                                      content=PROPFIND_BODY.encode("utf-8"))
    except httpx.HTTPError as exc:
        raise RelayError("接続先へ届きませんでした") from exc
    if response.status_code in (401, 403):
        raise RelayError("利用者名またはパスワードを確認してください")
    if response.status_code == 404:
        raise RelayError("そのフォルダは見つかりませんでした")
    if response.status_code >= 400:
        raise RelayError(f"フォルダを読み取れませんでした（{response.status_code}）")

    try:
        tree = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc:
        raise RelayError("接続先の応答を読み取れませんでした。WebDAV のURLか確認してください") from exc

    ns = {"d": "DAV:"}
    here = urlparse(target).path
    folders = []
    for entry in tree.findall("d:response", ns):
        href_node = entry.find("d:href", ns)
        if href_node is None or not href_node.text:
            continue
        href = href_node.text
        path = urlparse(href).path
        if unquote(path.rstrip("/")) == unquote(here.rstrip("/")):
            continue  # 自分自身
        if entry.find(".//d:resourcetype/d:collection", ns) is None:
            continue  # ファイルは出さない
        name = unquote(path.rstrip("/").rsplit("/", 1)[-1])
        if name:
            folders.append({"name": name, "url": urljoin(target, href if href.startswith("http") else path)})
    folders.sort(key=lambda item: item["name"])
    return folders
