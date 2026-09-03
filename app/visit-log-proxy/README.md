# visit-log-proxy

HTML編集ができないサードパーティ製 Web サービスに対して、透過プロキシ経由で
visit-log へアクセスログを記録するための代理計測ツール。

## 仕組み

1. ブラウザ → 本プロキシ(listen_port) → target_base へ無加工で中継
2. レスポンスを返し終えた後、別スレッドで visit-log の `/px.gif` にビーコン送信
3. `X-Forwarded-For` ヘッダーで実訪問者のIPを転送するので、visit-log 側で
   通常の計測と同じ集計ができる
4. ビーコン送信の失敗・遅延は daemon thread + 短timeout により対象サービスの
   応答をブロックしない

## サイトを追加する手順

`~/.config/visit-log-proxy/sites.json` に1エントリ追加して
`systemctl --user restart visit-log-proxy` するだけ。

```json
{
  "visit_log_base": "http://100.94.207.13:8526",
  "sites": [
    {
      "name": "対象を識別する名前 (visit-log 側の site名になる)",
      "listen_host": "127.0.0.1",
      "listen_port": "空いているポート",
      "target_base": "http://実際のサービスのbase URL"
    }
  ]
}
```

ブラウザからのアクセス先を `target_base` から `listen_port` に切り替える
(ブックマーク変更、あるいは手前にDNS/hostsで向けるなど)ことで計測対象にできる。

## 既知の制約

- 2026-09-03 時点で実運用検証済みなのは searxng (同一マシン) のみ。
  別マシン上のサービス (例: evo-x2 上の open-webui) へのクロスホスト適用は未検証。
- WebSocket やチャンク転送を多用するアプリでは中継が壊れる可能性がある
  (現状は単純な request/response の読み切り転送のみ)。
- 認証Cookieを使うアプリは、Originやポートが変わることで動作に影響する場合がある。
