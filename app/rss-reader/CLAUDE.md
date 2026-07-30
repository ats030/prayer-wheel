# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 起動

```bash
~/app/rss-reader.sh                      # ポート 8505 で起動
systemctl --user restart rss-reader      # サービスとして再起動
```

`PYTHONPATH=$HOME/app/rss-reader/src` を通したうえで `uv run uvicorn rss_reader.app:app` を実行する。
依存パッケージは `~/pyproject.toml`（`uv sync`）で管理する — このリポジトリに `requirements.txt` は置かない。

環境変数は `~/.env` から読む（`rss_reader/__init__.py` の `load_dotenv`。config.py が import 時に
環境変数を読むため、パッケージ初期化で先に読み込む必要がある）。systemd 側も `EnvironmentFile` で
同じファイルを渡している。

開発中は `--reload` を付けると Python の変更を拾う（静的ファイルのキャッシュバスターは
起動時に確定するため、CSS/JS を変えたら再起動する）。

## データの場所

すべて `~`（`RSS_READER_HOME` で変更可）配下の絶対パスで、旧 Streamlit 版と共有している。

| パス | 内容 |
|---|---|
| `~/data/feeds.json` | 購読フィードURLの一覧 |
| `~/data/bookmarks.json` | ブックマーク（タグ・メタ情報つき） |
| `~/data/feed_cache/*.json` | フィードごとの取得結果（meta + items + fetched_at） |
| `~/cache/` | diskcache（記事本文・LLMスコア・翻訳・興味プロファイル） |

## アーキテクチャ

サーバーレンダリング + バニラJS。htmx やビルド工程は使わない。

```
src/rss_reader/
├── app.py            FastAPI ルート（ページ・HTMLフラグメント・JSON API）
├── service.py        UI非依存の取得／集約／絞り込み／並び替え
├── jobs.py           バックグラウンドジョブ登録簿（進捗はポーリングで返す）
├── config.py         定数と絶対パス
├── core/             フィード処理（UI非依存。Streamlit 版からそのまま移植）
│   ├── detector.py     URL → フィードURL群の解決（5段階フォールバック）
│   ├── fetcher.py      requests.Session ラッパー
│   ├── parser.py       feedparser → FeedItem / FeedMeta
│   ├── feed_cache.py   フィード取得結果の永続化（mtime キーのメモ化つき）
│   ├── persistence.py  FeedStore（feeds.json）
│   ├── bookmarks.py    BookmarkStore（bookmarks.json）
│   ├── classifier.py   メディアタイプ判定・著者抽出
│   ├── extractor.py    記事本文抽出（trafilatura → readability → bs4）
│   ├── scorer.py       2段構えの記事スコアリング（下記参照）
│   ├── vocab.py        文脈つき正規表現の語彙（新規性/意外性/告知）
│   ├── profile.py      興味プロファイル（Obsidian 索引 → Ollama）
│   ├── llm.py          Ollama クライアント（JSON抽出・repair・clamp）
│   ├── tagger.py       自動タグ生成（Ollama → キーワード抽出フォールバック）
│   └── translator.py   英語記事の日本語化（RSS_TRANSLATE_TO_JA=1 で有効）
├── templates/        Jinja2（base / feed / new / bookmarks / _items / _item）
└── static/           linear.css（デザインシステム）, app.css, app.js
```

### 表示の流れ

初回リクエストはサーバーが1ページ分（`config.PAGE_SIZE`、既定100件）の HTML を描画する。
絞り込み・並び替えを変えると `app.js` が `/partials/items` を取得して `#list` を差し替え、
「もっと見る」は同じフラグメントを `offset` 付きで取得して追記する。テンプレートの記事行は
`_item.html` のマクロ1箇所だけに存在し、ページとフラグメントの両方から使う。

`GZipMiddleware` を有効にしているので、100件のリストは実測 140KB → 32KB になる。

### 記事行のメタ列

記事一覧の右側（スコア／フィード名／日時／再生時間／話数）は固定幅のグリッド列で、
行をまたいで縦に揃うようにしている。列構成は `_items.html` が `.items` に付ける
`with-feed` / `with-media` クラスで切り替える。

- `with-feed`: 複数フィード横断の一覧（新着）だけフィード名の列を持つ
- `with-media`: 再生時間・話数を**過半数の記事が持つとき**だけ列を確保する
  （`app._media_majority()`）。1件でも確保する実装にすると、ポッドキャストが数件
  混ざるだけの新着一覧で全行のタイトル幅を 130px 失う

判定は表示中のページではなく絞り込み後の全件で行う。ページ単位だと
「もっと見る」で追記した行だけ列がずれる。

### 重い処理はジョブにする

フィード全更新・Ollama スコアリング・タグ生成・興味プロファイル生成・フィード検出は
`jobs.start()` でワーカースレッドに投げ、`/api/jobs/{id}` をブラウザがポーリングする。
Streamlit 版の `st.progress` に相当するのが `base.html` の `#jobBar`。
ジョブ状態はプロセス内メモリのみ（再起動で消えるが、更新結果は逐次キャッシュに書かれている）。

### 記事スコアリング（`core/scorer.py`）

2段構え。他アプリの設計をそのまま踏襲している。

**第1段（全件・数ms）** — patent-miner/scorer.py と同型の加重合成。
各成分は 0..1、重みの合計で割るので重みを変えてもスケールが保たれる。

| 成分 | 内容 |
|---|---|
| novelty | 世界初・記録更新・買収・サービス終了など（`vocab.NOVELTY`） |
| surprise | 予想外・逆転・論争など（`vocab.SURPRISE`） |
| specificity | 単位つき数値の密度。バッチ内 p90 で対数正規化 |
| announce | 告知・宣伝（**負**）。加点軸に混ぜず合成後に乗算で減点 |
| relative | 同じフィード内での百分位。x-analyzer が母数で割るのと同じ狙い |

**ゲート → 第2段（上位N件のみ）** — writing/evaluate.py と同型の多軸JSON評価
（specificity / originality / promo）。promo は減算する。実測 約3.5秒/件なので
全1,800件では1.7時間かかる。旧実装は全件採点する作りだったため一度も実行されて
いなかった（スコアキャッシュが空だった）。

LLM は置き換えではなく**倍率**として効かせる（`×(1 ± w_llm)`）。中立なら素通し
なので、未採点の記事と採点済みの記事を同じ尺度で比較できる。

**スコアに入れないもの**: 鮮度（旧実装では重み0.4・総合との相関 +0.765 で、
重要度順が実質日付順になっていた）と、ブックマーク済みかどうか（39フィード中29が
対象で記事の84%に定数2.0点が付いていた）。どちらも UI のフィルタで表現する。

重みは `~/data/score_weights.json`（`/settings` 画面で編集）。配点を変えたら
`high_threshold`（🔥の閾値）を実データの p97 に再較正すること。

### 興味プロファイル（`core/profile.py`）

`~/.cache/writing/cognitive_index.json`（writing アプリが構築する Obsidian の
ローカル索引）から最近のノート見出しと頻出タグを読み、Ollama で要約する。
pCloud 上の vault は**直接読まない**。索引が無ければブックマークのみに退避する。

### キャッシュ

- フィード本体: `~/data/feed_cache/*.json`。読み出しは `feed_cache._read()` が mtime をキーに
  パース済み JSON をプロセス内に保持する（新着ページは全39フィード・約1,800記事を読むため）
- 記事本文・LLMスコア・翻訳・プロファイル: `diskcache`（`~/cache/`）

## 主なエンドポイント

| メソッド | パス | 用途 |
|---|---|---|
| GET | `/` | フィード画面（`?feed=<url>` で表示対象、`?llm=1` で LLM スコア反映） |
| GET | `/new` | 新着画面（全フィード横断） |
| GET | `/bookmarks` | ブックマーク画面 |
| GET | `/partials/items` | 記事一覧の HTML フラグメント |
| GET | `/api/article?url=` | 記事本文の抽出結果 |
| GET | `/api/jobs/{id}` | ジョブの進捗 |
| POST | `/api/feeds/detect` `/add` `/remove` `/refresh` `/refresh-all` | フィード管理 |
| POST | `/api/bookmarks/save` `/remove` `/suggest-tags` | ブックマーク管理 |
| POST | `/api/score` | 第2段。`{scope, url}` で対象を指定し上位N件を採点 |
| POST | `/api/profile/generate` | 興味プロファイルの生成 |
| GET | `/settings` | スコア配点の編集 |
| POST | `/api/settings` `/api/settings/reset` | 重みの保存・既定値化 |

## デザイン

`DESIGN.md` の Linear 系ダークテーマに従う。`static/linear.css` は writing アプリと共通の
デザインシステムで、rss-reader 固有のコンポーネントだけ `static/app.css` に置く。

## 変更履歴上の注意

2026-07 に Streamlit から FastAPI + バニラJS へ移行した。移行前の実装は
`~/pCloudDrive/Python/rss-reader/`（Streamlit 版）にそのまま残っている。


## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files
