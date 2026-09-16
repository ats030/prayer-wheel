# Design — Shiseki Map

`shiseki-map` は `onsen-map` の Go / Leaflet / SQLite / Wikipedia / Cloud Run 構成を
流用する姉妹アプリです。共通する視覚規約の正本は
[`omatsuri-map`](../omatsuri-map/DESIGN.md) とし、生成り・藍・朱の役割、Workbench
レイアウト、4px基準の余白、短い状態遷移を維持します。

## Domain-specific structure

- 検索: 名称・地域、都道府県、カテゴリ、時代、指定区分。
- 指定区分: 特別史跡、国指定、地方指定、未指定・不明。法的指定と一般的な歴史スポットを混同しない。
- マーカー: 指定区分を色で示し、同じ情報を凡例と詳細の文字でも示す。
- 詳細: 概要、写真、歴史、遺構・見どころ、アクセス、指定情報、出典、宿泊導線。
- 欠損値: 掲載対象から除外せず「未登録」または「情報なし」と表示する。

## Data and provenance

- 表示データは `scripts/fetch_shiseki.py` で生成する静的スナップショット。
- 国指定・特別史跡は文化庁の指定区分を正本とし、Wikidataを座標・名称・記事対応に使う。
- 広義史跡は座標と日本語Wikipedia記事を持つ遺跡、古墳、城跡等に限定する。
- 画像はWikimedia Commonsでライセンスを確認できるものだけを表示し、作者・ライセンス・出典を併記する。
- 利用条件の判断は `docs/tool-license.yaml` に記録する。

## Runtime differences

- 自己ホスト版は既定 port 8530。Cloud Runでは `PORT` を使用する。
- Cloud Runでは `SHISEKI_SUMMARY_DISABLE=1` とし、Wikipedia本文ブロックを表示する。
- `JALAN_A8MAT` がある場合のみ、都道府県別のじゃらん宿泊リンクを詳細下部に表示する。
- 全HTML entry pointに `data-site="shiseki-map"` のvisit-logタグを置く。Cloud Runから
  LAN内集計先へ到達できない点は `deploy-cloudrun.sh` に例外理由を記録する。
